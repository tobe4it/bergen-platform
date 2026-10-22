#!/usr/bin/env python3
"""Read-only, aggregate-only symlink diagnosis for the pinned Rocky 9.8 rootfs.

Never extracts, touches guest 701, emits archive names, or changes the import gate.
The structural audit remains the authoritative approval gate.
"""
from collections import Counter
import hashlib
import json
import os
import socket
import stat
import tarfile

import audit_rocky_lxc_rootfs as rootfs


def target_class(resolved):
    """Only fixed, non-identifying top-level classes reach operator output."""
    head = resolved.split("/", 1)[0]
    if head in ("proc", "sys", "dev", "run", "tmp"):
        return "runtime_tree"
    if head in ("etc", "usr", "var", "opt"):
        return head + "_tree"
    return "other_tree"


def diagnose_graph(names, links, implicit_directories):
    classes = Counter()
    missing = Counter()
    missing_parent = Counter()
    for name, target in links.items():
        prefix = "absolute" if target.startswith("/") else "relative"
        try:
            resolved = rootfs.follow_inside_root(
                name.rpartition("/")[0], target, links
            )
        except rootfs.AuditBlocked as exc:
            # The reason is one of the fixed audit error codes, not a path.
            reason = str(exc)
            rootfs.require(reason in (
                "SYMLINK_ESCAPES_ROOT",
                "INVALID_SYMLINK_TARGET",
                "SYMLINK_LOOP_OR_DEPTH",
            ), "UNKNOWN_RESOLUTION_FAILURE")
            classes[prefix + "_" + reason.lower()] += 1
            continue

        if not resolved:
            classes[prefix + "_root_target"] += 1
        elif resolved in names:
            classes[prefix + "_archived_target"] += 1
        elif resolved in implicit_directories:
            classes[prefix + "_implicit_directory"] += 1
        else:
            classes[prefix + "_dangling"] += 1
            missing[prefix + "_" + target_class(resolved)] += 1
            parent = resolved.rpartition("/")[0]
            parent_is_present = (
                not parent or parent in names or parent in implicit_directories
            )
            missing_parent["parent_present" if parent_is_present
                           else "parent_missing"] += 1

    return {
        "classification": dict(sorted(classes.items())),
        "dangling_target_classes": dict(sorted(missing.items())),
        "dangling_parent_classes": dict(sorted(missing_parent.items())),
        "symlinks_checked": len(links),
    }


def diagnostic():
    rootfs.require(os.geteuid() != 0, "REFUSE_ROOT_EXECUTION")
    rootfs.require(socket.gethostname().split(".")[0] == "bp-controller",
                   "UNEXPECTED_HOST")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    with os.fdopen(os.open(rootfs.ARCHIVE, flags), "rb") as handle:
        before = os.fstat(handle.fileno())
        rootfs.require(stat.S_ISREG(before.st_mode), "ARCHIVE_NOT_REGULAR")
        rootfs.require(before.st_size == rootfs.SIZE, "ARCHIVE_SIZE_MISMATCH")
        checksum = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
        rootfs.require(checksum.hexdigest() == rootfs.SHA256,
                       "ARCHIVE_SHA256_MISMATCH")
        handle.seek(0)
        names, links, implicit = set(), {}, set()
        with tarfile.open(fileobj=handle, mode="r|xz") as archive:
            for member in archive:
                name = rootfs.relative_name(member.name)
                if not name:
                    rootfs.require(member.isdir(), "NON_DIRECTORY_ARCHIVE_ROOT")
                    continue
                rootfs.require(name not in names, "DUPLICATE_MEMBER")
                names.add(name)
                rootfs.require(len(names) <= rootfs.MAX_FILES,
                               "TOO_MANY_MEMBERS")
                parts = name.split("/")
                implicit.update("/".join(parts[:i])
                                for i in range(1, len(parts)))
                if member.issym():
                    links[name] = member.linkname
        summary = diagnose_graph(names, links, implicit)
        after = os.fstat(handle.fileno())
        rootfs.require(
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "ARCHIVE_CHANGED_DURING_AUDIT",
        )
    return {
        "result": "ROCKY_LXC_ROOTFS_SYMLINK_DIAGNOSTIC_COMPLETE",
        "sha256_verified": True,
        **summary,
        "archive_extracted": False,
        "template_imported": False,
        "ct701_changed": False,
        "import_gate": "BLOCKED_PENDING_STRUCTURAL_AUDIT",
    }


if __name__ == "__main__":
    try:
        print(json.dumps(diagnostic(), sort_keys=True))
    except (rootfs.AuditBlocked, OSError, tarfile.TarError,
            UnicodeError, EOFError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, rootfs.AuditBlocked) else "ARCHIVE_READ_ERROR"
        print(json.dumps({
            "result": "ROCKY_LXC_ROOTFS_SYMLINK_DIAGNOSTIC_BLOCKED",
            "reason": reason,
            "archive_extracted": False,
            "ct701_changed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None
