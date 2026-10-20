#!/usr/bin/env python3
"""Read-only metadata inspection of the SHA-pinned Rocky 9.8 LXC tarball.

No extraction or execution. Emit aggregate numeric ownership and PAX counts,
never archive member names. Structural audit must pass on same immutable FD.
"""
from collections import Counter
import hashlib
import json
import os
import socket
import stat
import tarfile

import audit_rocky_lxc_rootfs as rootfs

MAX_CONTAINER_ID = 65535


def classify_owner(uid, gid):
    rootfs.require(isinstance(uid, int) and isinstance(gid, int)
                   and uid >= 0 and gid >= 0, "INVALID_UID_GID")
    return uid > MAX_CONTAINER_ID, gid > MAX_CONTAINER_ID


def inspect_pinned_idmap_metadata():
    rootfs.require(os.geteuid() != 0, "REFUSE_ROOT_EXECUTION")
    rootfs.require(socket.gethostname().split(".")[0] == "bp-controller",
                   "UNEXPECTED_HOST")
    fd = os.open(rootfs.ARCHIVE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        rootfs.require(stat.S_ISREG(before.st_mode), "ARCHIVE_NOT_REGULAR")
        rootfs.require(before.st_size == rootfs.SIZE, "ARCHIVE_SIZE_MISMATCH")
        sha = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
        rootfs.require(sha.hexdigest() == rootfs.SHA256,
                       "ARCHIVE_SHA256_MISMATCH")
        handle.seek(0)
        structure = rootfs.inspect_archive(
            handle, allow_pinned_exceptions=True)
        rootfs.require(
            structure["result"] == "ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS"
            and structure["pinned_missing_link_exception_count"] == 7,
            "ROOTFS_STRUCTURAL_RECHECK_FAILED",
        )

        handle.seek(0)
        members = 0
        min_uid, min_gid = None, None
        max_uid = max_gid = 0
        too_high_uid = too_high_gid = 0
        pax_members = 0
        pax_keys = Counter()
        xattr_members = 0
        sparse_members = 0
        with tarfile.open(fileobj=handle, mode="r|xz") as archive:
            for member in archive:
                members += 1
                uid_high, gid_high = classify_owner(member.uid, member.gid)
                too_high_uid += uid_high
                too_high_gid += gid_high
                min_uid = member.uid if min_uid is None else min(min_uid, member.uid)
                min_gid = member.gid if min_gid is None else min(min_gid, member.gid)
                max_uid, max_gid = max(max_uid, member.uid), max(max_gid, member.gid)
                if member.pax_headers:
                    pax_members += 1
                    pax_keys.update(member.pax_headers)
                    if any(key.startswith(("SCHILY.xattr.", "LIBARCHIVE.xattr."))
                           for key in member.pax_headers):
                        xattr_members += 1
                    if any(key.startswith("GNU.sparse.")
                           for key in member.pax_headers):
                        sparse_members += 1
        rootfs.require(members == (structure["regular_count"] +
                                  structure["directory_count"] +
                                  structure["hardlink_count"] +
                                  structure["symlink_count"]) or
                       members == (structure["regular_count"] +
                                   structure["directory_count"] +
                                   structure["hardlink_count"] +
                                   structure["symlink_count"] + 1),
                       "MEMBER_COUNT_MISMATCH")
        after = os.fstat(handle.fileno())
        rootfs.require(
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "ARCHIVE_CHANGED_DURING_AUDIT",
        )

    return {
        "result": "ROCKY_9_8_UID_GID_METADATA_REVIEW_COMPLETE",
        "sha256_verified": True,
        "structural_audit_passed": True,
        "archive_members": members,
        "minimum_uid": min_uid,
        "maximum_uid": max_uid,
        "minimum_gid": min_gid,
        "maximum_gid": max_gid,
        "uid_outside_default_mapping_count": too_high_uid,
        "gid_outside_default_mapping_count": too_high_gid,
        "members_with_pax_headers": pax_members,
        "members_with_xattrs": xattr_members,
        "members_with_sparse_pax": sparse_members,
        "pax_header_key_categories": {
            "xattr": sum(value for key, value in pax_keys.items()
                         if key.startswith(("SCHILY.xattr.", "LIBARCHIVE.xattr."))),
            "sparse": sum(value for key, value in pax_keys.items()
                          if key.startswith("GNU.sparse.")),
            "other": sum(value for key, value in pax_keys.items()
                         if not key.startswith((
                             "SCHILY.xattr.", "LIBARCHIVE.xattr.",
                             "GNU.sparse."))),
        },
        "default_idmap_compatibility": (
            too_high_uid == 0 and too_high_gid == 0),
        "archive_extracted": False,
        "new_guest_created": False,
        "ct701_changed": False,
        "pct_create_authorized": False,
    }


def main():
    try:
        print(json.dumps(inspect_pinned_idmap_metadata(), sort_keys=True))
    except (rootfs.AuditBlocked, OSError, tarfile.TarError,
            UnicodeError, EOFError, ValueError, TypeError) as exc:
        reason = (str(exc) if isinstance(exc, rootfs.AuditBlocked)
                  else "ARCHIVE_READ_ERROR")
        print(json.dumps({
            "result": "ROCKY_9_8_UID_GID_METADATA_AUDIT_BLOCKED",
            "reason": reason,
            "archive_extracted": False,
            "ct701_changed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
