#!/usr/bin/env python3
"""No-write, bounded inspection of SUID/SGID regular files in pinned Rocky rootfs.

Read metadata only. Never extract, execute archive payload, or touch PVE guests.
Only 14 publicly distributed system paths are emitted for human review.
"""
import hashlib
import json
import os
import socket
import stat
import tarfile

import audit_rocky_lxc_rootfs as rootfs

EXPECTED_PRIVILEGED_FILES = 14
MAX_OUTPUT_RECORDS = 32


def privileged_regular_record(member):
    """Return bounded metadata only for SUID/SGID regular archive members."""
    if not member.isfile() or not (member.mode & 0o6000):
        return None
    name = rootfs.relative_name(member.name)
    rootfs.require(bool(name), "INVALID_PRIVILEGED_MEMBER")
    rootfs.require(member.mode & ~0o7777 == 0, "INVALID_PRIVILEGED_MODE")
    rootfs.require(member.uid >= 0 and member.gid >= 0, "INVALID_PRIVILEGED_OWNER")
    return {
        "path": name,
        "mode": format(member.mode & 0o7777, "04o"),
        "uid": member.uid,
        "gid": member.gid,
        "setuid": bool(member.mode & 0o4000),
        "setgid": bool(member.mode & 0o2000),
        "world_writable": bool(member.mode & 0o002),
    }


def inspect():
    rootfs.require(os.geteuid() != 0, "REFUSE_ROOT_EXECUTION")
    rootfs.require(socket.gethostname().split(".")[0] == "bp-controller",
                   "UNEXPECTED_HOST")

    fd = os.open(rootfs.ARCHIVE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        rootfs.require(stat.S_ISREG(before.st_mode), "ARCHIVE_NOT_REGULAR")
        rootfs.require(before.st_size == rootfs.SIZE, "ARCHIVE_SIZE_MISMATCH")
        h = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
        rootfs.require(h.hexdigest() == rootfs.SHA256,
                       "ARCHIVE_SHA256_MISMATCH")
        handle.seek(0)

        full = rootfs.inspect_archive(handle, allow_pinned_exceptions=True)
        rootfs.require(full["result"] == "ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS",
                       "STRUCTURAL_AUDIT_NOT_PASSED")
        rootfs.require(full["pinned_missing_link_exception_count"] == 7,
                       "PINNED_LINK_COUNT_MISMATCH")
        rootfs.require(full["privileged_mode_regular_count"] ==
                       EXPECTED_PRIVILEGED_FILES,
                       "PRIVILEGED_FILE_COUNT_CHANGED")

        handle.seek(0)
        records = []
        with tarfile.open(fileobj=handle, mode="r|xz") as archive:
            for member in archive:
                row = privileged_regular_record(member)
                if row is not None:
                    records.append(row)
                    rootfs.require(len(records) <= MAX_OUTPUT_RECORDS,
                                   "TOO_MANY_PRIVILEGED_FILES")
        rootfs.require(len(records) == EXPECTED_PRIVILEGED_FILES,
                       "PRIVILEGED_FILE_COUNT_CHANGED")

        after = os.fstat(handle.fileno())
        rootfs.require(
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "ARCHIVE_CHANGED_DURING_AUDIT",
        )

    records.sort(key=lambda entry: entry["path"])
    rootfs.require(len({row["path"] for row in records}) == len(records),
                   "DUPLICATE_PRIVILEGED_PATH")
    return {
        "result": "ROCKY_ROOTFS_PRIVILEGED_MODE_REVIEW_REQUIRED",
        "sha256_verified": True,
        "structural_audit_passed": True,
        "privileged_file_count": len(records),
        "setuid_count": sum(row["setuid"] for row in records),
        "setgid_count": sum(row["setgid"] for row in records),
        "world_writable_privileged_count":
            sum(row["world_writable"] for row in records),
        "files_for_review": records,
        "archive_extracted": False,
        "template_imported": False,
        "template_import_authorized": False,
        "ct701_changed": False,
    }


def main():
    try:
        print(json.dumps(inspect(), sort_keys=True))
    except (rootfs.AuditBlocked, OSError, tarfile.TarError,
            UnicodeError, EOFError, ValueError) as exc:
        reason = (str(exc) if isinstance(exc, rootfs.AuditBlocked)
                  else "ARCHIVE_READ_ERROR")
        print(json.dumps({
            "result": "ROCKY_ROOTFS_PRIVILEGED_MODE_AUDIT_BLOCKED",
            "reason": reason,
            "archive_extracted": False,
            "ct701_changed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
