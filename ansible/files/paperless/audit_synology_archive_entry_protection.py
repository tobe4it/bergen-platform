#!/usr/bin/env python3
"""READ-ONLY DSM native ACL assessment of the ACTIVE protected archive tree.

The deployed archive is a sibling of scan inboxes under each Btrfs site root:
paperless-scan/.bergen-paperless-archive/{Familie,Eltern} and
homes/.bergen-paperless-archive/Privat/{thomas,nadja}.
Inspect native ACLs of every *actual parent* of archive entries, including
existing month folders containing PDFs. Never mutate, rename or open PDFs.
Static ACL inspection is not a substitute for effective DSM/SMB rename tests.
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
        if role == "user" and principal in (service_user, "root"):
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
        raise RuntimeError("ACTIVE_ARCHIVE_NATIVE_ACL_QUERY_FAILED")
    return parse_aces(r.stdout)


MONTH = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])\Z")


def protected_entry_targets(sources, service_uid, move):
    """Map configured sources to real same-device protected archive parents.

    Uses the worker's reviewed absolute/same-device resolver. This function
    only constructs and validates paths; it never provisions them.
    """
    expected = {"Eltern", "Familie", "Privat/thomas", "Privat/nadja"}
    if len(sources) != 4 or {scope for _, scope in sources} != expected:
        raise RuntimeError("INVALID_ARCHIVE_SCOPES")
    targets = {}
    def register(path, site, kind, source_dev):
        old = targets.get(path)
        value = (site, kind, source_dev)
        if old is not None and old != value:
            raise RuntimeError("CONFLICTING_PROTECTED_TARGET")
        targets[path] = value

    for source, scope in sources:
        parts = scope.split("/")
        site = move.SITE_BY_SCOPE[scope]
        source = Path(source)
        source_stat = source.lstat()
        if not stat.S_ISDIR(source_stat.st_mode):
            raise RuntimeError("UNSAFE_CONFIGURED_SOURCE")
        protected = move._validated_protected_scope(
            source, scope, service_uid)
        archive_root = protected.parents[len(parts) - 1]
        site_root = archive_root.parent
        if (archive_root.name != move.PROTECTED_ARCHIVE_DIR or
                site_root.name != site or
                protected != archive_root.joinpath(*parts) or
                site_root not in source.parents or
                source == site_root or
                source_stat.st_dev != protected.lstat().st_dev):
            raise RuntimeError("WRONG_ACTIVE_ARCHIVE_LOCATION")
        register(site_root, site, "SITE_ROOT", source_stat.st_dev)
        register(archive_root, site, "PROTECTED_ROOT", source_stat.st_dev)
        if len(parts) > 1:
            register(archive_root / parts[0], site,
                     "PROTECTED_INTERMEDIATE", source_stat.st_dev)
        register(protected, site, "PROTECTED_SCOPE", source_stat.st_dev)
    if len({site for site, kind, _ in targets.values()
            if kind == "SITE_ROOT"}) != 2:
        raise RuntimeError("MISSING_ARCHIVE_SITE")
    return targets


def existing_month_targets(scope, source_dev, service_uid, move):
    """Validate existing month directories and add their ACL parent targets."""
    months = []
    for name in os.listdir(scope):
        if not MONTH.fullmatch(name):
            raise RuntimeError("UNEXPECTED_PROTECTED_SCOPE_ENTRY")
        path = scope / name
        fd = move._check_dir(path, service_uid)
        try:
            if os.fstat(fd).st_dev != source_dev:
                raise RuntimeError("ARCHIVE_MONTH_DIFFERENT_DEVICE")
        finally:
            os.close(fd)
        months.append(path)
    return sorted(months)


def audit(parent):
    if (os.geteuid() != 0 or not parent.is_absolute()
            or parent == Path("/") or ".." in parent.parts):
        raise RuntimeError("ROOT_AND_VALID_STATE_PARENT_REQUIRED")
    binpath = parent / "bin"
    bs = binpath.lstat()
    if (not stat.S_ISDIR(bs.st_mode) or bs.st_uid != 0
            or stat.S_IMODE(bs.st_mode) != 0o755):
        raise RuntimeError("UNSAFE_ROOT_CODE_DIR")
    sys.path.insert(0, str(binpath))
    from synology_config import SETTINGS
    import synology_same_volume_archive_move as move
    if (SETTINGS["parent"] != parent or
            SETTINGS["sync_user"] != "paperless-sync"):
        raise RuntimeError("SITE_CONFIGURATION_MISMATCH")
    code = (binpath / "synology_same_volume_archive_move.py").lstat()
    if (not stat.S_ISREG(code.st_mode) or code.st_uid != 0
            or code.st_nlink != 1 or stat.S_IMODE(code.st_mode) != 0o644):
        raise RuntimeError("UNTRUSTED_PROTECTED_ARCHIVE_WORKER")
    service = pwd.getpwnam(SETTINGS["sync_user"])
    if service.pw_uid == 0:
        raise RuntimeError("INVALID_SERVICE_IDENTITY")
    tool = synoacl_tool()
    targets = protected_entry_targets(SETTINGS["sources"], service.pw_uid, move)
    for path, (site, kind, device) in list(targets.items()):
        if kind != "PROTECTED_SCOPE":
            continue
        for month in existing_month_targets(path, device, service.pw_uid, move):
            if month in targets:
                raise RuntimeError("DUPLICATE_ARCHIVE_MONTH")
            targets[month] = (site, "ARCHIVE_MONTH", device)

    risks = 0
    for path, (site, kind, source_dev) in sorted(
            targets.items(), key=lambda kv: str(kv[0])):
        entry = path.lstat()
        if (not stat.S_ISDIR(entry.st_mode) or
                entry.st_dev != source_dev or
                (kind == "SITE_ROOT" and entry.st_uid != 0) or
                (kind != "SITE_ROOT" and
                 (entry.st_uid != service.pw_uid or
                  stat.S_IMODE(entry.st_mode) != 0o700))):
            raise RuntimeError("UNSAFE_ACTIVE_ARCHIVE_PARENT")
        if kind != "SITE_ROOT":
            fd = move._check_dir(path, service.pw_uid)
        else:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY |
                         os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino, opened.st_uid,
                 opened.st_mode) !=
                (entry.st_dev, entry.st_ino, entry.st_uid,
                 entry.st_mode)):
                raise RuntimeError("ARCHIVE_PARENT_RACED")
            aces = get_aces(tool, path)
        finally:
            os.close(fd)
        grants = unsafe_parent_grants(aces, SETTINGS["sync_user"])
        print("AUDITED_ACTIVE_ARCHIVE_PARENT", site, kind,
              "ACE_COUNT", len(aces))
        if grants:
            print("BLOCKER", site, kind,
                  "NONADMIN_POTENTIAL_DELETE_GRANTS", len(grants))
            risks += len(grants)
    print("ACTIVE_PROTECTED_ARCHIVE_PARENTS_AUDITED", len(targets))
    print("POTENTIAL_NATIVE_DELETE_GRANTS", risks)
    print("ARCHIVE_ENTRY_PROTECTION_BLOCKED" if risks else
          "ARCHIVE_ENTRY_PROTECTION_NEEDS_EFFECTIVE_TEST")
    print("DSM_SMB_EFFECTIVE_RENAME_NOT_TESTED")
    print("ARCHIVE_COMMIT_NOT_AUTHORIZED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_synology_archive_entry_protection.py STATE_PARENT")
    audit(Path(sys.argv[1]))
