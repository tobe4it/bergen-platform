#!/usr/bin/env python3
"""Plan or explicitly create one private Paperless deletion-decision directory.

Invoked only inside the verified Paperless LXC, via stdin from Ansible.
No receipt reads/writes, no document operations, no archive activation.
The --apply operation must additionally be gated by an explicit Ansible var.
"""
import os
import pwd
import stat
import sys

PARENT = "/var/lib/paperless-ingest"
CHILD = "deletion-decisions"
USER = "paperless-ingest"
EXPECTED_UID = 997
EXPECTED_GID = 988
EXPECTED_PARENT_MODE = 0o750
EXPECTED_CHILD_MODE = 0o700


def inspect():
    account = pwd.getpwnam(USER)
    if (account.pw_uid != EXPECTED_UID or account.pw_gid != EXPECTED_GID):
        raise RuntimeError("UNEXPECTED_INGEST_IDENTITY")
    parent = os.lstat(PARENT)
    root = os.lstat("/")
    if (not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != 0 or parent.st_gid != EXPECTED_GID
            or stat.S_IMODE(parent.st_mode) != EXPECTED_PARENT_MODE
            or parent.st_dev != root.st_dev):
        raise RuntimeError("UNSAFE_PARENT_OR_UNEXPECTED_ROOTFS")
    fd = os.open(PARENT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        live = os.fstat(fd)
        if (live.st_dev != parent.st_dev or live.st_ino != parent.st_ino
                or live.st_uid != 0 or live.st_gid != EXPECTED_GID
                or stat.S_IMODE(live.st_mode) != EXPECTED_PARENT_MODE):
            raise RuntimeError("PARENT_CHANGED")
        try:
            current = os.stat(CHILD, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return fd, False
        if (not stat.S_ISDIR(current.st_mode)
                or current.st_uid != EXPECTED_UID
                or current.st_gid != EXPECTED_GID
                or stat.S_IMODE(current.st_mode) != EXPECTED_CHILD_MODE):
            raise RuntimeError("UNSAFE_OR_CONFLICTING_JOURNAL_DIRECTORY")
        return fd, True
    except BaseException:
        os.close(fd)
        raise


def main(action):
    if action not in ("plan", "apply"):
        raise ValueError("UNKNOWN_ACTION")
    fd, exists = inspect()
    try:
        if action == "plan":
            print("ALREADY_SECURE" if exists else "READY_TO_CREATE")
            print("EXPECTED_OWNER_UID", EXPECTED_UID)
            print("EXPECTED_GROUP_GID", EXPECTED_GID)
            print("EXPECTED_MODE", "0700")
            print("ROOTFS_DEVICE_VERIFIED")
            print("NO_FILES_CHANGED")
            return
        if os.geteuid() != 0:
            raise RuntimeError("ROOT_REQUIRED_FOR_DIRECTORY_CREATION")
        if exists:
            print("ALREADY_SECURE")
            print("NO_FILES_CHANGED")
            return
        # A root-only directory is safe even if chown fails. On such
        # failure, stop for manual review; never silently repair it.
        os.mkdir(CHILD, EXPECTED_CHILD_MODE, dir_fd=fd)
        os.chown(CHILD, EXPECTED_UID, EXPECTED_GID,
                 dir_fd=fd, follow_symlinks=False)
        os.fsync(fd)
    finally:
        os.close(fd)
    verify_fd, verified = inspect()
    os.close(verify_fd)
    if not verified:
        raise RuntimeError("POST_CREATION_VERIFICATION_FAILED")
    print("CREATED_AND_VERIFIED")
    print("NO_JOURNAL_WRITTEN")
    print("NO_RECEIPTS_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("USAGE: script plan|apply")
    main(sys.argv[1])
