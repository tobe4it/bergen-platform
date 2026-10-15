#!/usr/bin/env python3
"""Read-only candidate discovery for root-controlled archives on each NAS device.

Scans configured source ancestors to find the nearest existing filesystem-device
boundary, proposes a sibling archive *at* that boundary, and checks native DSM
parent ACLs for explicit non-admin delete-child grants. No mkdir, chmod, ACL
change, rename, touching PDFs, or root commit-gate creation.

A clean report is NOT authorization for a live archive move: Btrfs subvolume
identity, effective SMB/LDAP access, service traversal and backup/restore must
still be tested. Missing/ambiguous boundaries fail closed.
"""
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SCOPES = frozenset(("Familie", "Eltern", "Privat/thomas", "Privat/nadja"))
CANDIDATE = ".bergen-paperless-archive"
ADMIN_GROUPS = frozenset(("administrators", "administrators@bergen.intern"))
ACE = re.compile(
    r"(?:^|\s)(?:\?\s*)?\[[0-9]+\]\s+"
    r"(group|user):([^:]+):(allow|deny):([rwxpdDaARWcCo-]{13,15}):"
    r"([fdin-]{4})\s+\(level:[0-9]+\)"
)
LINUX_MODE = re.compile(r"\(synoacltool\.c,\s*[0-9]+\)It's Linux mode\Z")


def require(value, code):
    if not value:
        raise RuntimeError(code)


def checked_directory(path):
    stat_before = path.lstat()
    require(stat.S_ISDIR(stat_before.st_mode), "UNSAFE_OR_SYMLINK_DIRECTORY")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        stat_after = os.fstat(fd)
        require((stat_before.st_dev, stat_before.st_ino,
                 stat_before.st_uid, stat_before.st_mode) ==
                (stat_after.st_dev, stat_after.st_ino,
                 stat_after.st_uid, stat_after.st_mode),
                "DIRECTORY_REPLACED")
    finally:
        os.close(fd)
    return stat_before


def device_boundary(source):
    """Return highest same-st_dev ancestor; reject unsafe/no boundary."""
    first = checked_directory(source)
    current = source
    for _ in range(32):
        if current.parent == current:
            raise RuntimeError("DEVICE_ROOT_NOT_SEPARATE_FROM_FILESYSTEM_ROOT")
        parent_st = checked_directory(current.parent)
        if parent_st.st_dev != first.st_dev:
            if current == source:
                raise RuntimeError("SOURCE_IS_DEVICE_ROOT_NOT_SAFE_ARCHIVE_PARENT")
            return current
        current = current.parent
    raise RuntimeError("DEVICE_ANCESTRY_TOO_DEEP")


def acl_excerpt(line):
    """Bounded, single-line diagnostics; no escaping to a second log record."""
    return "".join(c if c.isprintable() else "?" for c in line)[:240]


def parse_native_aces(output):
    if not isinstance(output, str) or len(output) > 64000:
        raise RuntimeError("UNSAFE_ACL_OUTPUT")
    entries = []
    for line in output.splitlines():
        if "allow:" not in line and "deny:" not in line:
            continue
        match = ACE.search(line)
        if match is None:
            raise RuntimeError("UNRECOGNIZED_NATIVE_ACL_ENTRY " + acl_excerpt(line))
        entries.append(match.groups())
        if len(entries) > 100:
            raise RuntimeError("ACL_ENTRY_LIMIT")
    require(entries, "NATIVE_ACL_EMPTY")
    return entries


def parent_delete_grants(aces, sync_user):
    bad = []
    for role, principal, effect, permissions, _inherit in aces:
        if effect != "allow":
            continue
        if role == "group" and principal in ADMIN_GROUPS:
            continue
        if role == "user" and principal in ("root", sync_user):
            continue
        # 'd' delete, 'D' delete-child; a conventional writable
        # executable parent can also support renames.
        if (permissions[4] == "d" or permissions[5] == "D"
                or (permissions[1] == "w" and permissions[2] == "x")):
            bad.append(role + ":" + principal)
    return bad


def evaluate_parent(stat_info, tool_result, sync_user):
    """Return (classification, risky grants). Classification is cautious."""
    if not stat.S_ISDIR(stat_info.st_mode) or stat_info.st_uid != 0:
        return "UNSAFE_UNOWNED_PARENT", []
    text = (tool_result.stdout + "\n" + tool_result.stderr).strip()
    if tool_result.returncode == 0:
        entries = parse_native_aces(tool_result.stdout)
        grants = parent_delete_grants(entries, sync_user)
        if grants:
            return "PARENT_HAS_NONADMIN_DELETE_GRANTS", grants
        return "NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT", []
    if tool_result.returncode == 255 and LINUX_MODE.fullmatch(text):
        if stat.S_IMODE(stat_info.st_mode) & 0o022:
            return "POSIX_PARENT_WRITABLE_BY_OTHERS", []
        return "ROOT_POSIX_PARENT_NO_GROUP_WRITE", []
    return "UNKNOWN_PARENT_ACL_STATE", []


def acl_tool():
    for path in ("/usr/syno/bin/synoacltool",
                 "/usr/syno/sbin/synoacltool", shutil.which("synoacltool")):
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("SYNOACLTOOL_MISSING")


def inspect(parent):
    require(os.geteuid() == 0 and parent.is_absolute()
            and ".." not in parent.parts and parent != Path("/"),
            "ROOT_AND_ABSOLUTE_STATE_PARENT_REQUIRED")
    binpath = parent / "bin"
    bininfo = checked_directory(binpath)
    require(bininfo.st_uid == 0 and stat.S_IMODE(bininfo.st_mode) == 0o755,
            "UNSAFE_CONFIG_CODE_ROOT")
    sys.path.insert(0, str(binpath))
    from synology_config import SETTINGS
    require(SETTINGS["parent"] == parent and len(SETTINGS["sources"]) == 4,
            "SITE_CONFIGURATION_MISMATCH")
    user = pwd.getpwnam(SETTINGS["sync_user"])
    require(user.pw_uid != 0, "UNSAFE_SYNC_IDENTITY")
    tool = acl_tool()
    by_device = {}
    scopes_seen = set()
    blockers = 0
    for source, scope in SETTINGS["sources"]:
        require(scope in SCOPES and scope not in scopes_seen, "INVALID_SCOPE")
        scopes_seen.add(scope)
        source_info = checked_directory(source)
        root = device_boundary(source)
        root_info = checked_directory(root)
        require(root_info.st_dev == source_info.st_dev, "CROSS_DEVICE_CANDIDATE")
        proposed = root / CANDIDATE
        # An existing path is NOT adopted by this audit.
        present = proposed.exists() or proposed.is_symlink()
        result = subprocess.run(
            [tool, "-get", str(root)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=20)
        unknown_line = None
        try:
            classification, grants = evaluate_parent(
                root_info, result, SETTINGS["sync_user"])
        except RuntimeError as exc:
            if not str(exc).startswith("UNRECOGNIZED_NATIVE_ACL_ENTRY "):
                raise
            # Reject the candidate but continue inspecting the other
            # independent scopes; return all forensic evidence in one run.
            classification = "UNRECOGNIZED_NATIVE_ACL_ENTRY"
            grants = []
            unknown_line = str(exc).split(" ", 1)[1]
        print("SCOPE", scope)
        print("SOURCE_DEVICE", source_info.st_dev)
        print("PROPOSED_DEVICE_ROOT", str(root))
        print("PROPOSED_ARCHIVE", str(proposed))
        print("PARENT_ACL_STATUS", classification)
        if unknown_line is not None:
            print("UNRECOGNIZED_PARENT_ACE", scope, unknown_line)
        print("ARCHIVE_CANDIDATE", "EXISTS_REVIEW_REQUIRED" if present else "ABSENT")
        if present:
            print("BLOCKER", scope, "EXISTING_CANDIDATE_REQUIRES_MANUAL_REVIEW")
            blockers += 1
        if classification not in (
                "NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT",
                "ROOT_POSIX_PARENT_NO_GROUP_WRITE"):
            print("BLOCKER", scope, classification)
            blockers += 1
        for principal in grants:
            print("BLOCKER", scope, "PARENT_RENAME_RIGHT", principal)
        if (source_info.st_dev in by_device
                and by_device[source_info.st_dev] != root):
            print("BLOCKER", scope, "AMBIGUOUS_DEVICE_ROOT")
            blockers += 1
        by_device[source_info.st_dev] = root
        print("EFFECTIVE_IDENTITIES_AND_SUBVOLUME_ID_REVIEW_REQUIRED", scope)
    require(scopes_seen == SCOPES, "MISSING_SCOPE")
    print("CANDIDATE_DEVICE_COUNT", len(by_device))
    print("ARCHIVE_PARENT_BLOCKERS", blockers)
    print("ARCHIVE_PARENT_CANDIDATES_BLOCKED" if blockers else
          "ARCHIVE_PARENT_CANDIDATES_NEED_EFFECTIVE_TEST")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_synology_protected_archive_candidates.py STATE_PARENT")
    inspect(Path(sys.argv[1]))
