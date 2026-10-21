#!/usr/bin/env python3
"""No-write, no-atime, no-symlink-follow Rocky 9.8 CT790 release inspection.

Injected via python3 -c: no host script copy, no guest start or mount.
Only read small known regular files from the already mounted CT790 ZFS rootdir.
"""
import json
import os
import re
import socket
import stat
import sys
from contextlib import ExitStack

MAX_RELEASE_BYTES = 4096
DIR_FLAGS = (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
             | os.O_CLOEXEC | os.O_NOATIME)
FILE_FLAGS = (os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
              | os.O_NOATIME | os.O_NONBLOCK)


class ReadBlocked(Exception):
    pass


def demand(condition, code):
    if not condition:
        raise ReadBlocked(code)


def small_regular_file(parentfd, name):
    fd = os.open(name, FILE_FLAGS, dir_fd=parentfd)
    try:
        st = os.fstat(fd)
        demand(stat.S_ISREG(st.st_mode), "NOT_REGULAR_RELEASE_FILE")
        demand(0 < st.st_size <= MAX_RELEASE_BYTES, "RELEASE_SIZE_UNEXPECTED")
        data = os.read(fd, MAX_RELEASE_BYTES + 1)
        demand(len(data) <= MAX_RELEASE_BYTES and len(data) == st.st_size,
               "RELEASE_READ_INCOMPLETE")
        return data.decode("utf-8")
    finally:
        os.close(fd)


def read_release_tree(root):
    """Pure file-descriptor based inspection; leaves file timestamps unchanged."""
    with ExitStack() as opened:
        rootfd = os.open(root, DIR_FLAGS)
        opened.callback(os.close, rootfd)
        demand(stat.S_ISDIR(os.fstat(rootfd).st_mode), "ROOTFS_NOT_DIRECTORY")
        etcfd = os.open("etc", DIR_FLAGS, dir_fd=rootfd)
        opened.callback(os.close, etcfd)
        usrfd = os.open("usr", DIR_FLAGS, dir_fd=rootfd)
        opened.callback(os.close, usrfd)
        libfd = os.open("lib", DIR_FLAGS, dir_fd=usrfd)
        opened.callback(os.close, libfd)

        release = small_regular_file(etcfd, "rocky-release")
        os_release = small_regular_file(libfd, "os-release")
        st_link = os.stat("os-release", dir_fd=etcfd, follow_symlinks=False)
        demand(stat.S_ISLNK(st_link.st_mode), "ETC_OS_RELEASE_NOT_SYMLINK")
        demand(os.readlink("os-release", dir_fd=etcfd) == "../usr/lib/os-release",
               "ETC_OS_RELEASE_SYMLINK_CHANGED")

        demand(release.strip() == "Rocky Linux release 9.8 (Blue Onyx)",
               "ROCKY_RELEASE_MISMATCH")
        lines = os_release.splitlines()
        ids = [line for line in lines if line.startswith("ID=")]
        versions = [line for line in lines if line.startswith("VERSION_ID=")]
        demand(ids == ['ID="rocky"'], "OS_RELEASE_ID_MISMATCH")
        demand(versions == ['VERSION_ID="9.8"'], "OS_RELEASE_VERSION_MISMATCH")

        return {
            "result": "ROCKY_9_8_CT790_ROOTFS_RELEASE_READ_ONLY_VERIFIED",
            "os_id": "rocky",
            "os_version_id": "9.8",
            "rocky_release_verified": True,
            "os_release_symlink_verified": True,
            "rootfs_files_read": 2,
            "files_written": 0,
            "filesystem_mount_changed": False,
            "ct790_started": False,
            "ct701_changed": False,
            "pct_start_authorized": False,
            "pct_template_authorized": False,
            "runtime_tested": False,
        }


def main():
    try:
        demand(len(sys.argv) == 2, "EXPECTED_ONE_ROOTDIR_PATH")
        demand(os.geteuid() == 0 and
               socket.gethostname().split(".")[0] == "venombox",
               "HOST_IDENTITY_MISMATCH")
        root = sys.argv[1]
        demand(re.fullmatch(r"/rpool/data/subvol-790-disk-[0-9]+", root) is not None,
               "UNAPPROVED_ROOTFS_PATH")
        demand(hasattr(os, "O_NOATIME"), "NOATIME_UNAVAILABLE")
        print(json.dumps(read_release_tree(root), sort_keys=True))
    except (ReadBlocked, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, ReadBlocked) else "RELEASE_OS_READ_ERROR"
        print(json.dumps({
            "result": "ROCKY_9_8_CT790_ROOTFS_RELEASE_READ_ONLY_BLOCKED",
            "reason": reason,
            "files_written": 0,
            "ct790_started": False,
            "ct701_changed": False,
        }, sort_keys=True))
        sys.exit(1)


if __name__ == "__main__":
    main()
