#!/usr/bin/env python3
"""Root-mediated Synology hidden archive provisioner, opt-in only.

--audit is read-only. --prepare may create only the scoped hidden directories
and one sender-private journal directory. It DOES NOT touch any existing PDF,
receipt, watcher, activation gate, backup, ACL or purge. Native DSM ACLs still
require independent inspection; POSIX 0700 is not sufficient evidence.
"""
import argparse
import os
import pwd
import stat
import sys
from pathlib import Path


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def check_dir(path, uid=None, mode=None):
    before = path.lstat()
    require(stat.S_ISDIR(before.st_mode) and before.st_nlink >= 1
            and (uid is None or before.st_uid == uid)
            and (mode is None or stat.S_IMODE(before.st_mode) == mode),
            "UNSAFE_ARCHIVE_DIRECTORY")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        now = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_mode, before.st_uid) ==
                (now.st_dev, now.st_ino, now.st_mode, now.st_uid),
                "ARCHIVE_DIRECTORY_RACED")
        return now
    finally:
        os.close(fd)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def inspect(parent, prepare=False):
    require(os.geteuid() == 0, "ROOT_REQUIRED")
    require(isinstance(parent, Path) and parent.is_absolute()
            and parent != Path("/") and ".." not in parent.parts
            and parent.parent != parent, "UNSAFE_SITE_PARENT")
    check_dir(parent, uid=0, mode=0o755)
    bindir = parent / "bin"
    check_dir(bindir, uid=0, mode=0o755)
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    require(SETTINGS["parent"] == parent, "SITE_CONFIG_MISMATCH")
    account = pwd.getpwnam(SETTINGS["sync_user"])
    require(account.pw_uid != 0, "UNSAFE_SERVICE_ACCOUNT")
    state = SETTINGS["state"]
    check_dir(state, uid=account.pw_uid, mode=0o700)
    gate = parent / "archive-move.enabled"
    require(not gate.exists() and not gate.is_symlink(),
            "ARCHIVE_COMMIT_GATE_ALREADY_PRESENT")
    targets = [(state / "archive-move-journal", state, "JOURNAL")]
    for folder, scope in SETTINGS["sources"]:
        require(scope in ("Familie", "Eltern", "Privat/thomas", "Privat/nadja"),
                "UNAPPROVED_SCOPE")
        check_dir(folder)
        targets.append((folder / ".paperless-archive", folder, scope))
    seen = set()
    for dest, base, scope in targets:
        require(str(dest) not in seen, "DUPLICATE_ARCHIVE_DIRECTORY")
        seen.add(str(dest))
        current = check_dir(base)
        try:
            info = check_dir(dest, uid=account.pw_uid, mode=0o700)
            require(info.st_dev == current.st_dev, "ARCHIVE_CROSSES_DEVICE")
            print("ARCHIVE_EXISTS", scope)
        except FileNotFoundError:
            if not prepare:
                print("ARCHIVE_MISSING", scope)
                continue
            # No general chown/chmod of user-supplied paths and no recursive
            # changes. Symlinks / pre-existing unexpected dirs fail closed.
            os.mkdir(dest, 0o700)
            os.chown(dest, account.pw_uid, account.pw_gid)
            os.chmod(dest, 0o700)
            sync_dir(base)
            info = check_dir(dest, uid=account.pw_uid, mode=0o700)
            require(info.st_dev == current.st_dev, "ARCHIVE_CROSSES_DEVICE")
            print("ARCHIVE_CREATED", scope)
        if scope != "JOURNAL":
            print("NATIVE_DSM_ACL_REVIEW_REQUIRED", scope)
    print("ARCHIVE_GATE_ABSENT")
    print("NO_SCAN_OR_RECEIPT_FILES_CHANGED")
    print("ARCHIVE_COMMIT_NOT_AUTHORIZED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("parent")
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--audit", action="store_true")
    commands.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    inspect(Path(args.parent), prepare=args.prepare)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        print("HIDDEN_ARCHIVE_SETUP_FAILED", str(exc).split(" ", 1)[0], file=sys.stderr)
        sys.exit(1)
