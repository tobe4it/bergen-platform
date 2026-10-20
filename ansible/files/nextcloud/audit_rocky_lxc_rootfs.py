#!/usr/bin/env python3
"""Read-only structural gate for the exact pinned Linux Containers Rocky 9.8 rootfs.

No extraction, command execution, archive mutation, or guest operation.
Output is a small non-identifying JSON status; no archive member names are logged.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tarfile

ARCHIVE = Path("/home/ansible/rocky9-lxc-20261018/rootfs.tar.xz")
SHA256 = "1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5"
SIZE = 107425612
MAX_FILES = 400000
MAX_BYTES = 16 * 1024**3
MAX_LINK_DEPTH = 48


class AuditBlocked(Exception):
    pass


def require(condition, code):
    if not condition:
        raise AuditBlocked(code)


def relative_name(name):
    require(bool(name) and not name.startswith("/") and "\x00" not in name, "UNSAFE_MEMBER_NAME")
    while name.startswith("./"):
        name = name[2:]
    if name == ".":
        return ""
    parts = name.split("/")
    require(all(part not in ("", ".", "..") for part in parts),
            "UNSAFE_MEMBER_SEGMENT")
    require(not any(any(ord(char) < 32 or ord(char) == 127 for char in part)
                    for part in parts), "CONTROL_CHAR_IN_MEMBER")
    return "/".join(parts)


def follow_inside_root(start, link_target, links):
    """Resolve symlinks using Linux rootfs semantics; never touch the host filesystem."""
    require(bool(link_target) and "\x00" not in link_target
            and not any(ord(c) < 32 or ord(c) == 127 for c in link_target),
            "INVALID_SYMLINK_TARGET")
    pending = list(link_target.split("/"))
    resolved = [] if link_target.startswith("/") else (start.split("/") if start else [])
    traversals = 0
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            require(bool(resolved), "SYMLINK_ESCAPES_ROOT")
            resolved.pop()
            continue
        resolved.append(part)
        current = "/".join(resolved)
        if current in links:
            traversals += 1
            require(traversals <= MAX_LINK_DEPTH, "SYMLINK_LOOP_OR_DEPTH")
            target = links[current]
            require(bool(target) and "\x00" not in target
                    and not any(ord(c) < 32 or ord(c) == 127 for c in target),
                    "INVALID_SYMLINK_TARGET")
            if target.startswith("/"):
                resolved = []
            else:
                resolved.pop()
            pending = target.split("/") + pending
    return "/".join(resolved)


def inspect_archive(handle):
    names = set()
    types = {}
    regular_seen = set()
    symlinks = {}
    implicit_directories = set()
    dirs, regular, hardlinks, total_bytes, executable_privileged = 0, 0, 0, 0, 0
    absolute_symlinks = 0
    backslash_regular = 0
    release = {}
    with tarfile.open(fileobj=handle, mode="r|xz") as archive:
        for member in archive:
            name = relative_name(member.name)
            if not name:
                require(member.isdir(), "NON_DIRECTORY_ARCHIVE_ROOT")
                continue
            require(name not in names, "DUPLICATE_MEMBER")
            names.add(name)
            parts = name.split("/")
            for idx in range(1, len(parts)):
                implicit_directories.add("/".join(parts[:idx]))
            require(len(names) <= MAX_FILES, "TOO_MANY_MEMBERS")
            require(member.uid >= 0 and member.gid >= 0,
                    "INVALID_UID_GID")
            require(member.size >= 0, "NEGATIVE_MEMBER_SIZE")
            total_bytes += member.size
            require(total_bytes <= MAX_BYTES, "TOO_LARGE_UNCOMPRESSED")
            require(member.mode & ~0o7777 == 0, "UNEXPECTED_MODE_BITS")
            if member.isdir():
                dirs += 1
                types[name] = "directory"
            elif member.isfile():
                regular += 1
                regular_seen.add(name)
                types[name] = "regular"
                if "\\" in name:
                    # On Linux the backslash is a filename character, not a separator.
                    backslash_regular += 1
                if member.mode & 0o6000:
                    executable_privileged += 1
                if name in ("etc/rocky-release", "usr/lib/os-release"):
                    require(member.size <= 4096, "RELEASE_MARKER_TOO_LARGE")
                    content = archive.extractfile(member)
                    require(content is not None, "RELEASE_MARKER_UNREADABLE")
                    release[name] = content.read(4097).decode("utf-8")
            elif member.islnk():
                # TAR hardlink targets are root-relative archive member names,
                # never relative to the hardlink's parent directory.
                target = relative_name(member.linkname)
                require(bool(target) and target in regular_seen,
                        "HARDLINK_TARGET_NOT_EARLIER_REGULAR")
                require(member.size == 0, "HARDLINK_NONZERO_SIZE")
                hardlinks += 1
                types[name] = "hardlink"
            elif member.issym():
                symlinks[name] = member.linkname
                types[name] = "symlink"
                if member.linkname.startswith("/"):
                    absolute_symlinks += 1
            else:
                # Device nodes, FIFOs and unknown types never pass this gate.
                raise AuditBlocked("UNREVIEWED_NONREGULAR_MEMBER")
    require(regular > 1000 and dirs > 100, "INCOMPLETE_ROOTFS")
    require(release.get("etc/rocky-release", "").strip()
            == "Rocky Linux release 9.8 (Blue Onyx)",
            "ROCKY_RELEASE_MISMATCH")
    require('ID="rocky"' in release.get("usr/lib/os-release", "")
            and 'VERSION_ID="9.8"' in release["usr/lib/os-release"],
            "OS_RELEASE_MISMATCH")
    require("etc/os-release" in symlinks
            and symlinks["etc/os-release"] == "../usr/lib/os-release",
            "OS_RELEASE_SYMLINK_MISMATCH")
    require(not (implicit_directories & symlinks.keys()),
            "MEMBER_UNDER_SYMLINK")
    require(not (implicit_directories &
                 {name for name, kind in types.items()
                  if kind in ("regular", "hardlink")}),
            "MEMBER_UNDER_NON_DIRECTORY")
    for name, target in symlinks.items():
        parent = name.rpartition("/")[0]
        resolved = follow_inside_root(parent, target, symlinks)
        require(bool(resolved), "LINK_TARGET_ARCHIVE_ROOT")
        require(resolved in names or resolved in implicit_directories,
                "DANGLING_SYMLINK")
    return {
        "result": "ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS",
        "rocky_version": "9.8",
        "sha256_verified": True,
        "regular_count": regular,
        "directory_count": dirs,
        "hardlink_count": hardlinks,
        "symlink_count": len(symlinks),
        "absolute_symlink_count": absolute_symlinks,
        "backslash_named_regular_count": backslash_regular,
        "privileged_mode_regular_count": executable_privileged,
        "hardlink_targets_verified": True,
        "devices_fifos_allowed": False,
        "archive_extracted": False,
        "template_imported": False,
        "ct701_changed": False,
        "next_gate": "Review mode counts and offline PVE import design",
    }


def audit(path=ARCHIVE, expected_sha=SHA256, expected_size=SIZE):
    require(os.geteuid() != 0, "REFUSE_ROOT_EXECUTION")
    require(socket.gethostname().split(".")[0] == "bp-controller",
            "UNEXPECTED_HOST")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode), "ARCHIVE_NOT_REGULAR")
        require(before.st_size == expected_size, "ARCHIVE_SIZE_MISMATCH")
        digest = hashlib.sha256()
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
        require(digest.hexdigest() == expected_sha, "ARCHIVE_SHA256_MISMATCH")
        handle.seek(0)
        result = inspect_archive(handle)
        after = os.fstat(handle.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "ARCHIVE_CHANGED_DURING_AUDIT")
        return result


def main():
    try:
        require(len(sys.argv) == 1, "ARGUMENTS_NOT_ALLOWED")
        result = audit()
        print(json.dumps(result, sort_keys=True))
    except (AuditBlocked, OSError, tarfile.TarError,
            UnicodeError, EOFError, ValueError) as exc:
        code = str(exc) if isinstance(exc, AuditBlocked) else "ARCHIVE_READ_ERROR"
        print(json.dumps({"result": "ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_BLOCKED",
                          "reason": code, "archive_extracted": False,
                          "ct701_changed": False}, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
