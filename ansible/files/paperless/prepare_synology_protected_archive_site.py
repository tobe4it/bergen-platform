#!/usr/bin/env python3
"""Opt-in and site-scoped EMPTY protected archive root provisioning on Synology.

Default --audit only. --prepare creates no scan files, changes no receipts or
existing ACLs, never moves PDFs, and never creates archive-move.enabled.

Sites "homes" and "paperless-scan" are INDEPENDENT. Each site must pass its
own root-owned, same-device, native-ACL no-nonadmin-delete-grants preflight.
POSIX 0700 directories created here are not a live archive authorization.
"""
import argparse
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SITE_SCOPES = {
    "homes": frozenset(("Privat/thomas", "Privat/nadja")),
    "paperless-scan": frozenset(("Eltern", "Familie")),
}
ARCHIVE_NAME = ".bergen-paperless-archive"
NATIVE_ACE = re.compile(
    r"(?:^|\s)(?:\?\s*)?\[[0-9]+\]\s+"
    r"(group|user):([^:]+):(allow|deny):([rwxpdDaARWcCo-]{13,15}):"
    r"([fdin-]{4})\s+\(level:[0-9]+\)"
)
SPECIAL_ACE = re.compile(
    r"(?:^|\s)(?:\?\s*)?\[[0-9]+\]\s+"
    r"(owner|everyone)::(allow|deny):([rwxpdDaARWcCo-]{13,15}):"
    r"([fdin-]{4})\s+\(level:[0-9]+\)"
)
LINUX_MODE = re.compile(r"\(synoacltool\.c,\s*[0-9]+\)It's Linux mode\Z")
ADMIN_GROUPS = frozenset(("administrators", "administrators@bergen.intern"))


def require(test, message):
    if not test:
        raise RuntimeError(message)


def inspect_dir(path, uid=None, mode=None, device=None):
    before = path.lstat()
    require(stat.S_ISDIR(before.st_mode), "UNSAFE_DIRECTORY_TYPE")
    require(uid is None or before.st_uid == uid, "UNSAFE_DIRECTORY_OWNER")
    require(mode is None or stat.S_IMODE(before.st_mode) == mode,
            "UNSAFE_DIRECTORY_MODE")
    require(device is None or before.st_dev == device, "CROSS_DEVICE")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_uid, before.st_mode) ==
                (after.st_dev, after.st_ino, after.st_uid, after.st_mode),
                "DIRECTORY_CHANGED")
    finally:
        os.close(fd)
    return before


def device_root(path):
    expected = inspect_dir(path).st_dev
    current = path
    for _ in range(32):
        require(current.parent != current, "DEVICE_ROOT_AMBIGUOUS")
        next_info = inspect_dir(current.parent)
        if next_info.st_dev != expected:
            require(current != path, "SOURCE_IS_DEVICE_ROOT")
            return current
        current = current.parent
    raise RuntimeError("DEVICE_ROOT_DEPTH_EXCEEDED")


def parse_parent_access(output):
    """Conservative classification; owner grants require separate st_uid=0."""
    require(isinstance(output, str) and len(output) <= 64000,
            "UNSAFE_NATIVE_ACL_RESPONSE")
    matches = 0
    for line in output.splitlines():
        if "allow:" not in line and "deny:" not in line:
            continue
        item = NATIVE_ACE.search(line)
        if item:
            role, principal, effect, perms, _flags = item.groups()
        else:
            item = SPECIAL_ACE.search(line)
            require(item is not None, "UNRECOGNIZED_NATIVE_ACE")
            role, effect, perms, _flags = item.groups()
            principal = ""
        matches += 1
        require(matches <= 100, "ACL_ENTRY_LIMIT")
        if effect == "deny" or role == "owner":
            continue
        if role == "group" and principal in ADMIN_GROUPS:
            continue
        if role == "user" and principal in ("root", "paperless-sync"):
            continue
        if (perms[4] == "d" or perms[5] == "D"
                or (perms[1] == "w" and perms[2] == "x")):
            raise RuntimeError("NONADMIN_PARENT_DELETE_GRANT")
    require(matches > 0, "MISSING_PARENT_ACL")


def parent_protection(root, tool):
    info = inspect_dir(root, uid=0)
    response = subprocess.run(
        [tool, "-get", str(root)],
        check=False, text=True, capture_output=True,
        encoding="utf-8", errors="replace", timeout=20)
    if response.returncode == 0:
        parse_parent_access(response.stdout)
        return "NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT"
    combined = (response.stdout + "\n" + response.stderr).strip()
    if response.returncode == 255 and LINUX_MODE.fullmatch(combined):
        require(stat.S_IMODE(info.st_mode) & 0o022 == 0,
                "POSIX_PARENT_WRITABLE_BY_NONOWNER")
        return "ROOT_POSIX_PARENT_NO_GROUP_WRITE"
    raise RuntimeError("UNKNOWN_PARENT_ACL")


def synoacl_tool():
    for candidate in ("/usr/syno/bin/synoacltool", "/usr/syno/sbin/synoacltool",
                      shutil.which("synoacltool")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("SYNOACLTOOL_NOT_FOUND")


def validate_private_directory(path, uid, dev, tool):
    info = inspect_dir(path, uid=uid, mode=0o700, device=dev)
    require(info.st_nlink >= 1, "INVALID_ARCHIVE_LINK_COUNT")
    result = subprocess.run(
        [tool, "-get", str(path)], check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=20)
    output = (result.stdout + "\n" + result.stderr).strip()
    require(result.returncode == 255 and LINUX_MODE.fullmatch(output),
            "PRIVATE_ARCHIVE_NATIVE_ACL_REVIEW_REQUIRED")


def verify_empty_site_tree(archive, scopes, owner, device, tool):
    """Read-only verification of a precisely empty, private staged site.

    Until the worker and import proof gate are released, ANY unexpected entry,
    including a PDF, hidden file or symlink, is an explicit blocker.
    """
    expected = {archive: set()}
    for scope in scopes:
        parent = archive
        for part in scope.split("/"):
            child = parent / part
            expected[parent].add(part)
            expected.setdefault(child, set())
            parent = child
    for path, permitted in expected.items():
        validate_private_directory(path, owner, device, tool)
        with os.scandir(path) as stream:
            names = {entry.name for entry in stream}
        require(names == permitted, "ARCHIVE_TREE_NOT_EMPTY_OR_UNEXPECTED_ENTRY")
    return len(expected)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stage_empty(path, owner, group, dev, tool):
    if path.exists() or path.is_symlink():
        validate_private_directory(path, owner, dev, tool)
        print("PROTECTED_ARCHIVE_EXISTS", path.name)
        return
    # Parent already root-owned and checked against nonadmin rename/delete.
    # O_EXCL equivalent for mkdir: existing path must never be overwritten.
    os.mkdir(path, mode=0o700)
    os.chown(path, owner, group)
    os.chmod(path, 0o700)
    sync_dir(path.parent)
    validate_private_directory(path, owner, dev, tool)
    print("PROTECTED_ARCHIVE_CREATED", path.name)


def inspect(parent, site, prepare=False):
    require(os.geteuid() == 0 and parent.is_absolute()
            and parent != Path("/") and ".." not in parent.parts,
            "ROOT_AND_ABSOLUTE_STATE_PARENT_REQUIRED")
    inspect_dir(parent, uid=0, mode=0o755)
    bindir = parent / "bin"
    inspect_dir(bindir, uid=0, mode=0o755)
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    require(SETTINGS["parent"] == parent and
            SETTINGS["sync_user"] == "paperless-sync",
            "UNSAFE_SITE_CONFIGURATION")
    user = pwd.getpwnam(SETTINGS["sync_user"])
    require(user.pw_uid != 0, "UNSAFE_SERVICE_IDENTITY")
    require(len(SETTINGS["sources"]) == 4, "UNEXPECTED_SOURCE_COUNT")
    gate = parent / "archive-move.enabled"
    require(not gate.exists() and not gate.is_symlink(),
            "ARCHIVE_MOVE_GATE_MUST_REMAIN_ABSENT")
    tool = synoacl_tool()
    wanted = SITE_SCOPES[site]
    sources = [(folder, scope) for folder, scope in SETTINGS["sources"]
               if scope in wanted]
    require({scope for _, scope in sources} == wanted
            and len(sources) == 2, "MISSING_SITE_SCOPES")
    roots, devices = set(), set()
    for folder, scope in sources:
        source = inspect_dir(folder)
        root = device_root(folder)
        roots.add(root)
        devices.add(source.st_dev)
        require(inspect_dir(root, uid=0).st_dev == source.st_dev,
                "WRONG_DEVICE_ROOT")
        # Obsolete hidden archive directories must be empty; never touch them.
        obsolete = folder / ".paperless-archive"
        obsolete_st = inspect_dir(obsolete, uid=user.pw_uid,
                                  mode=0o700, device=source.st_dev)
        require(obsolete_st.st_nlink >= 1, "UNSAFE_OBSOLETE_HIDDEN_ARCHIVE")
        with os.scandir(obsolete) as stream:
            require(next(stream, None) is None, "OBSOLETE_HIDDEN_ARCHIVE_NOT_EMPTY")
    require(len(roots) == len(devices) == 1,
            "SELECTED_SITE_NOT_SINGLE_DEVICE")
    root = next(iter(roots))
    device = next(iter(devices))
    protection = parent_protection(root, tool)
    archive = root / ARCHIVE_NAME
    print("SELECTED_SITE", site)
    print("DEVICE_ROOT", str(root))
    print("SOURCE_DEVICE", device)
    print("PARENT_ACL_STATUS", protection)
    print("PROTECTED_ARCHIVE_ROOT", str(archive))
    print("PROTECTED_ARCHIVE_CANDIDATE", "EXISTS" if (archive.exists() or archive.is_symlink()) else "ABSENT")
    if not prepare:
        if archive.exists() or archive.is_symlink():
            count = verify_empty_site_tree(
                archive, wanted, user.pw_uid, device, tool)
            print("PROTECTED_ARCHIVE_EMPTY_TREE_VERIFIED", site, count)
        else:
            print("PROTECTED_ARCHIVE_NOT_YET_STAGED", site)
        print("PREPARE_DISABLED")
        print("NO_FILES_CHANGED")
        print("ARCHIVE_COMMIT_NOT_AUTHORIZED")
        return
    # Create only private, empty structure for selected site. These names
    # cannot be renamed by nonadmin writers in the checked parent.
    stage_empty(archive, user.pw_uid, user.pw_gid, device, tool)
    for _folder, scope in sources:
        current = archive
        for part in scope.split("/"):
            current = current / part
            stage_empty(current, user.pw_uid, user.pw_gid, device, tool)
    count = verify_empty_site_tree(
        archive, wanted, user.pw_uid, device, tool)
    print("PROTECTED_ARCHIVE_EMPTY_TREE_VERIFIED", site, count)
    print("PROTECTED_SITE_PREPARED", site)
    print("NO_SCAN_OR_RECEIPT_FILES_CHANGED")
    print("ARCHIVE_GATE_ABSENT")
    print("ARCHIVE_COMMIT_NOT_AUTHORIZED")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("state_parent")
    p.add_argument("--site", choices=tuple(SITE_SCOPES), required=True)
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--audit", action="store_true")
    modes.add_argument("--prepare", action="store_true")
    args = p.parse_args()
    try:
        inspect(Path(args.state_parent), args.site, prepare=args.prepare)
    except (OSError, RuntimeError, ValueError) as exc:
        print("PROTECTED_ARCHIVE_STAGE_BLOCKED", str(exc).split(" ", 1)[0],
              file=sys.stderr)
        sys.exit(1)
