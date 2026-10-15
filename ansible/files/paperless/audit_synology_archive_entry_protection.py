#!/usr/bin/env python3
"""READ-ONLY DSM ACL assessment of hidden archive *directory entry* protection.

Linux 0700 on .paperless-archive protects contents but does not prevent users
with delete-child privilege on the parent scan directory from renaming/removing
the hidden archive itself. This script detects potential grants; it never
renames anything, and is intentionally not an authorization to move PDFs.
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
ACE = re.compile(
    r"(?:^|\s)(?:\?\s*)?\[[0-9]+\]\s+"
    r"(group|user):([^:]+):(allow|deny):([rwxpdDaARWcCo-]{13,15}):"
    r"([fdin-]{4})\s+\(level:[0-9]+\)"
)
ADMIN_GROUPS = frozenset(("administrators", "administrators@bergen.intern"))


def parse_aces(output):
    """Return a strict listing of reported ACEs; unknown output fails closed."""
    if not isinstance(output, str) or len(output) > 64000:
        raise RuntimeError("UNSAFE_ACL_OUTPUT")
    rows = []
    for line in output.splitlines():
        if "allow:" not in line and "deny:" not in line:
            continue
        match = ACE.search(line)
        if match is None:
            raise RuntimeError("UNPARSEABLE_ACL_ACE")
        role, principal, effect, perms, inherit = match.groups()
        if len(perms) < 6:
            raise RuntimeError("MALFORMED_ACL_PERMISSIONS")
        rows.append((role, principal, effect, perms, inherit))
        if len(rows) > 100:
            raise RuntimeError("ACL_TOO_MANY_ENTRIES")
    if not rows:
        raise RuntimeError("NO_ACL_ENTRIES")
    return rows


def unsafe_parent_grants(aces, service_user):
    """Conservatively report any non-admin explicit allow granting deletion.

    Deny ACEs and ACL ordering/effective identities require separate checks,
    so the presence of a risky allow is a blocker, not a proof of actual access.
    """
    risks = []
    for role, principal, effect, perms, _inherit in aces:
        if effect != "allow":
            continue
        if role == "group" and principal in ADMIN_GROUPS:
            continue
        if role == "user" and principal == service_user:
            continue
        # 'D' is delete-child on the scan directory, 'd' is delete
        # permission on the scan directory itself. 'w'+'x' also
        # indicates conventional parent rename risk with writable dirs.
        if perms[5] == "D" or perms[4] == "d" or (
                perms[1] == "w" and perms[2] == "x"):
            risks.append((role, principal))
    return risks


def synoacl_tool():
    for path in ("/usr/syno/bin/synoacltool", "/usr/syno/sbin/synoacltool",
                 shutil.which("synoacltool")):
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("SYNOACLTOOL_UNAVAILABLE")


def get_aces(tool, directory):
    r = subprocess.run([tool, "-get", str(directory)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=20, check=False)
    if r.returncode != 0:
        raise RuntimeError("SOURCE_NATIVE_ACL_QUERY_FAILED")
    return parse_aces(r.stdout)


def audit(parent):
    if (os.geteuid() != 0 or not parent.is_absolute()
            or parent == Path("/") or ".." in parent.parts):
        raise RuntimeError("ROOT_AND_VALID_STATE_PARENT_REQUIRED")
    binpath = parent / "bin"
    bs = binpath.lstat()
    if not stat.S_ISDIR(bs.st_mode) or bs.st_uid != 0 or stat.S_IMODE(bs.st_mode) != 0o755:
        raise RuntimeError("UNSAFE_ROOT_CODE_DIR")
    sys.path.insert(0, str(binpath))
    from synology_config import SETTINGS
    if SETTINGS["parent"] != parent:
        raise RuntimeError("SITE_CONFIGURATION_MISMATCH")
    service = pwd.getpwnam(SETTINGS["sync_user"])
    if service.pw_uid == 0 or len(SETTINGS["sources"]) != 4:
        raise RuntimeError("INVALID_SERVICE_OR_SCOPES")
    tool = synoacl_tool()
    seen = set()
    blocked = 0
    for source, scope in SETTINGS["sources"]:
        if scope not in SCOPES or scope in seen:
            raise RuntimeError("INVALID_OR_DUPLICATE_SCOPE")
        seen.add(scope)
        root = source.lstat()
        hidden = (source / ".paperless-archive").lstat()
        if (not stat.S_ISDIR(root.st_mode) or not stat.S_ISDIR(hidden.st_mode)
                or hidden.st_uid != service.pw_uid
                or stat.S_IMODE(hidden.st_mode) != 0o700
                or root.st_dev != hidden.st_dev):
            raise RuntimeError("UNSAFE_ARCHIVE_ROOT " + scope)
        aces = get_aces(tool, source)
        grants = unsafe_parent_grants(aces, SETTINGS["sync_user"])
        print("SCOPE", scope)
        print("SOURCE_ACE_COUNT", len(aces))
        for role, principal in grants:
            # No plaintext scan filenames or archive contents are printed.
            print("BLOCKER", scope, "SOURCE_DELETE_OR_RENAME_RIGHT", role + ":" + principal)
            blocked += 1
        if not grants:
            print("SOURCE_ACL_NO_OBVIOUS_NONADMIN_DELETE_GRANT", scope)
        print("EFFECTIVE_DSM_SMB_AND_RENAME_TEST_REQUIRED", scope)
    if seen != SCOPES:
        raise RuntimeError("MISSING_EXPECTED_SCOPES")
    print("RISKY_SOURCE_ACL_GRANTS", blocked)
    print("ARCHIVE_ENTRY_PROTECTION_BLOCKED" if blocked else
          "ARCHIVE_ENTRY_PROTECTION_NEEDS_EFFECTIVE_TEST")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_synology_archive_entry_protection.py STATE_PARENT")
    audit(Path(sys.argv[1]))
