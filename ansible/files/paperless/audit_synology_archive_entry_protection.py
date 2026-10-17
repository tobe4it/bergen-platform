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
# Native DSM ACLs include empty-name special principals and optional
# whitespace inside the level field. Require a whole-record match.
ACE = re.compile(
    r"^\s*(?:\?\s*)?\[[0-9]+\]\s+"
    r"(group|user|owner|everyone|system):([^:]*):"
    r"(allow|deny):([rwxpdDaARWcCo-]{13,15}):"
    r"([fdin-]{4})\s+\(level:\s*[0-9]+\)\s*"
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
        match = ACE.fullmatch(line)
        if match is None:
            raise RuntimeError("UNPARSEABLE_ACL_ACE")
        role, principal, effect, perms, inherit = match.groups()
        if ((role in ("group", "user") and not principal) or
                (role in ("owner", "everyone", "system") and principal)):
            raise RuntimeError("UNSUPPORTED_ACL_PRINCIPAL")
        if len(perms) < 6:
            raise RuntimeError("MALFORMED_ACL_PERMISSIONS")
        rows.append((role, principal, effect, perms, inherit))
        if len(rows) > 100:
            raise RuntimeError("ACL_TOO_MANY_ENTRIES")
    if not rows:
        raise RuntimeError("NO_ACL_ENTRIES")
    return rows


def unsafe_parent_grants(aces, service_user):
    """Conservatively report any non-admin or global allow granting deletion.

    Deny ACEs and ACL ordering/effective identities require separate checks,
    so the presence of a risky allow is a blocker, not a proof of actual access.
    """
    risks = []
    for role, principal, effect, perms, _inherit in aces:
        if effect != "allow":
            continue
        # The owner:: principal resolves to the UID already checked for
        # each protected directory (root at site root, sync user elsewhere).
        if role == "owner":
            continue
        if role == "group" and principal in ADMIN_GROUPS:
            continue
        if role == "user" and principal in (service_user, "root"):
            continue
        # Neither 'everyone' nor 'system' is an exempt administrator here.
        # D = delete-child, d = delete, w+x = parent write and traverse.
        if perms[5] == "D" or perms[4] == "d" or (
                perms[1] == "w" and perms[2] == "x"):
            risks.append((role, principal or "<special>"))
    return risks


def synoacl_tool():
    for path in ("/usr/syno/bin/synoacltool", "/usr/syno/sbin/synoacltool",
                 shutil.which("synoacltool")):
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("SYNOACLTOOL_UNAVAILABLE")


def native_acl_failure_class(returncode, stdout, stderr):
    """Classify failures without emitting native ACL content or identities."""
    if type(returncode) is not int or returncode == 0:
        raise RuntimeError("INVALID_NATIVE_ACL_FAILURE")
    raw = (stdout + "\n" + stderr).casefold()
    if any(token in raw for token in (
            "no acl", "acl not found", "does not have acl",
            "acl does not exist", "without acl")):
        label = "NO_NATIVE_ACL_REPORTED"
    elif any(token in raw for token in (
            "not support", "unsupported", "operation not supported")):
        label = "ACL_UNSUPPORTED_REPORTED"
    elif any(token in raw for token in (
            "permission denied", "access denied", "not permitted")):
        label = "ACL_ACCESS_DENIED_REPORTED"
    elif any(token in raw for token in (
            "no such file", "not found", "does not exist")):
        label = "ACL_PATH_NOT_FOUND_REPORTED"
    else:
        label = "UNCLASSIFIED_NATIVE_ACL_ERROR"
    return "RC_" + str(returncode) + "_" + label


# Deliberately narrow exception: observed DSM "It's Linux mode" readout.
# All other native-tool failures remain hard blockers, including generic
# missing-ACL messages, arbitrary exit 255, mixed errors, and timeouts.
LINUX_MODE_OUTPUT = re.compile(
    r"\\(synoacltool[.]c,\\s*[0-9]+\\)\\s*It's Linux mode\\Z")


def exact_linux_mode_readout(result):
    return (
        result.returncode == 255 and result.stderr == "" and
        isinstance(result.stdout, str) and
        LINUX_MODE_OUTPUT.fullmatch(result.stdout.strip()) is not None
    )


def get_aces(tool, directory):
    r = subprocess.run([tool, "-get", str(directory)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=20, check=False)
    if r.returncode != 0:
        if exact_linux_mode_readout(r):
            return None  # Explicit POSIX-only marker, NEVER an empty ACL list.
        raise RuntimeError(
            "ACTIVE_ARCHIVE_NATIVE_ACL_QUERY_FAILED_" +
            native_acl_failure_class(r.returncode, r.stdout, r.stderr))
    return parse_aces(r.stdout)


def require_posix_only_archive_parent(kind, info, uid):
    """A native-less archive child is safe only with independently checked 0700.

    Site roots must be inspected as DSM ACLs to protect the archive *entry*.
    """
    if (kind not in ("PROTECTED_ROOT", "PROTECTED_INTERMEDIATE",
                     "PROTECTED_SCOPE", "ARCHIVE_MONTH") or
            not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) != 0o700):
        raise RuntimeError("POSIX_ARCHIVE_PARENT_NOT_VERIFIED")


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
    posix_only = 0
    native_site_roots = set()
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
            try:
                aces = get_aces(tool, path)
            except RuntimeError as error:
                # Site/kind are fixed enumerations, not ACL principal names,
                # paths, original PDF filenames or native tool output.
                print("NATIVE_ACL_READ_BLOCKED", site, kind, str(error),
                      flush=True)
                raise RuntimeError("NATIVE_ACL_READ_BLOCKED") from None
        finally:
            os.close(fd)
        if aces is None:
            # The precise native tool's Linux-mode response means POSIX
            # semantics, not a passed DSM ACL. Site root still requires
            # a positive native ACL audit for delete-child protections.
            require_posix_only_archive_parent(kind, entry, service.pw_uid)
            if site not in native_site_roots:
                raise RuntimeError("SITE_ROOT_NATIVE_ACL_NOT_YET_VERIFIED")
            posix_only += 1
            print("AUDITED_ACTIVE_ARCHIVE_PARENT", site, kind,
                  "POSIX_0700_LINUX_MODE")
            continue
        grants = unsafe_parent_grants(aces, SETTINGS["sync_user"])
        if kind == "SITE_ROOT":
            if site in native_site_roots:
                raise RuntimeError("DUPLICATE_NATIVE_SITE_ROOT")
            native_site_roots.add(site)
        print("AUDITED_ACTIVE_ARCHIVE_PARENT", site, kind,
              "ACE_COUNT", len(aces))
        if grants:
            print("BLOCKER", site, kind,
                  "NONADMIN_POTENTIAL_DELETE_GRANTS", len(grants))
            risks += len(grants)
    if native_site_roots != {"homes", "paperless-scan"}:
        raise RuntimeError("SITE_ROOT_NATIVE_ACL_NOT_VERIFIED")
    print("NATIVE_SITE_ROOT_ACLS_VERIFIED", len(native_site_roots))
    print("POSIX_0700_ARCHIVE_PARENTS_VERIFIED", posix_only)
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
