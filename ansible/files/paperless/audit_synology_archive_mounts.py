#!/usr/bin/env python3
"""Read-only NAS mount topology for choosing a private, same-filesystem archive.

A shared scanner folder is NOT an approved quarantine location merely because
a hidden child would have mode 0700. Never creates directories or changes ACLs.
"""
import os
import pwd
import stat
import sys
from pathlib import Path


def decode_mount_field(value):
    # Linux mountinfo escapes spaces, tabs, newlines and backslashes as octal.
    for encoded, plain in (("\\040", " "), ("\\011", "\t"),
                           ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(encoded, plain)
    return value


def mount_table():
    records = []
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        left, marker, right = line.partition(" - ")
        if not marker:
            continue
        fields, rest = left.split(), right.split()
        if len(fields) < 5 or len(rest) < 2:
            continue
        records.append((Path(decode_mount_field(fields[4])), fields[2],
                        rest[0], decode_mount_field(rest[1])))
    return records


def mounted_at(path, mounts):
    absolute = path.resolve(strict=True)
    candidates = [m for m in mounts if absolute == m[0] or m[0] in absolute.parents]
    if not candidates:
        raise RuntimeError("MOUNT_NOT_FOUND " + str(path))
    return max(candidates, key=lambda m: len(m[0].parts))


def inspect(parent):
    if (not parent.is_absolute() or ".." in parent.parts or parent == Path("/")
            or str(parent) != os.path.normpath(str(parent))):
        raise RuntimeError("INVALID_PARENT")
    if os.geteuid() != 0:
        raise RuntimeError("ROOT_READ_ONLY_MOUNT_AUDIT_REQUIRED")
    bindir = parent / "bin"
    bs = bindir.lstat()
    if (not stat.S_ISDIR(bs.st_mode) or bs.st_uid != 0
            or stat.S_IMODE(bs.st_mode) != 0o755):
        raise RuntimeError("UNSAFE_CODE_DIRECTORY")
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    account = pwd.getpwnam(SETTINGS["sync_user"])
    if account.pw_uid == 0:
        raise RuntimeError("UNSAFE_SYNC_IDENTITY")
    mounts = mount_table()
    targets = [("STATE_PARENT", parent), ("CURRENT_ARCHIVE", parent / "paperless-archive")]
    targets.extend((scope, folder) for folder, scope in SETTINGS["sources"])
    for scope, path in targets:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("UNSAFE_DIRECTORY " + scope)
        mountpoint, major_minor, fstype, _source = mounted_at(path, mounts)
        print("SCOPE", scope)
        print("PATH", str(path))
        print("DEVICE", info.st_dev)
        print("MOUNTPOINT", str(mountpoint))
        print("MOUNT_DEVICE", major_minor)
        print("FSTYPE", fstype)
        print("OWNER", info.st_uid, info.st_gid)
        print("MODE", oct(stat.S_IMODE(info.st_mode)))
        print("ARCHIVE_LOCATION_APPROVED", "NO")
    print("REVIEW_REQUIRED", "SEPARATE_ROOT_CONTROLLED_ARCHIVE_LOCATION_PER_FILESYSTEM")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_synology_archive_mounts.py STATE_PARENT")
    inspect(Path(sys.argv[1]))
