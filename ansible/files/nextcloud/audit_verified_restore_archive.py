#!/usr/bin/env python3
"""Read-only audit of one pinned Synology archive staged on venombox.

Never extracts files, prints document names, exposes config values, touches
the guest, or connects to any production service.
"""
import gzip
import hashlib
import json
import posixpath
from pathlib import Path
import re
import socket
import stat
import sys
import tarfile

ROOT = Path("/var/lib/vz/nextcloud-restore-test")
MAX_ARCHIVE = 60 * 1024**3
MAX_MEMBERS = 1_000_000
MAX_SQL_BYTES = 2 * 1024**3
EXPECTED_ROOTS = {"html", "nextcloud.sql.gz", "BACKUP-MANIFEST.txt"}


class AuditError(Exception):
    pass


def require(cond, label):
    if not cond:
        raise AuditError(label)


def in_html(path):
    return path == "html" or path.startswith("html/")


def validate_symbolic_links(entries, links):
    """Safely resolve links in TAR namespace, without filesystem access.

    Do not pre-normalize a link target: treating .. before resolving a
    preceding symlink can incorrectly classify an escaping path as safe.
    No archive member may have a symlink as a parent. All targets must
    eventually resolve to an existing member inside the html tree.
    """
    from collections import deque

    for path in entries:
        pieces = path.split("/")
        for i in range(1, len(pieces)):
            require("/".join(pieces[:i]) not in links,
                    "SYMLINK_USED_AS_ARCHIVE_PARENT")

    for path, target in links.items():
        require(target and not target.startswith("/") and "\\" not in target
                and "\x00" not in target, "UNSAFE_SYMLINK_TARGET")
        pending = deque(posixpath.dirname(path).split("/") + target.split("/"))
        resolved = []
        visited = set()
        hops = 0
        while pending:
            piece = pending.popleft()
            if piece in ("", "."):
                continue
            if piece == "..":
                require(len(resolved) > 1, "SYMLINK_ESCAPE")
                resolved.pop()
                continue
            resolved.append(piece)
            require(resolved[0] == "html", "SYMLINK_ESCAPE")
            prefix = "/".join(resolved)
            if prefix in links:
                hops += 1
                require(hops <= 40, "SYMLINK_CHAIN_DEPTH_EXCEEDED")
                require(prefix not in visited, "SYMLINK_CYCLE")
                visited.add(prefix)
                next_target = links[prefix]
                require(next_target and not next_target.startswith("/")
                        and "\\" not in next_target and "\x00" not in next_target,
                        "UNSAFE_SYMLINK_TARGET")
                resolved.pop()
                pending.extendleft(reversed(next_target.split("/")))
        final_target = "/".join(resolved)
        require(in_html(final_target), "SYMLINK_ESCAPE")
        require(final_target in entries, "DANGLING_SYMLINK_TARGET")


def inspect(archive, ident, digest):
    require(re.fullmatch(r"20\d{6}T\d{6}Z-\d+", ident), "INVALID_SNAPSHOT_ID")
    require(re.fullmatch(r"[0-9a-f]{64}", digest), "INVALID_DIGEST")
    require(archive.is_file() and not archive.is_symlink(), "ARCHIVE_NOT_REGULAR")
    st = archive.stat()
    require(1024 * 1024 < st.st_size < MAX_ARCHIVE, "UNEXPECTED_ARCHIVE_SIZE")
    require(st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o600,
            "ARCHIVE_PERMISSIONS_UNSAFE")
    seen = set()
    links = {}
    regular_files = 0
    directories = 0
    total_content_bytes = 0
    manifest_member = None
    sql_member = None

    hashed = hashlib.sha256()
    with archive.open("rb") as src:
        while True:
            block = src.read(4 * 1024 * 1024)
            if not block:
                break
            hashed.update(block)
    require(hashed.hexdigest() == digest, "PINNED_SHA256_MISMATCH")

    try:
        with tarfile.open(archive, "r:gz") as tar:
            for item in tar:
                raw = item.name
                path = raw.rstrip("/")
                pieces = path.split("/")
                require(path and not path.startswith("/") and "\\" not in path,
                        "UNSAFE_ARCHIVE_PATH")
                require(all(p not in {"", ".", ".."} for p in pieces),
                        "UNSAFE_ARCHIVE_SEGMENT")
                require(pieces[0] in EXPECTED_ROOTS, "UNEXPECTED_TOP_LEVEL_ENTRY")
                require(pieces[0] == "html" or len(pieces) == 1,
                        "UNEXPECTED_ROOT_FILE_LOCATION")
                require(path not in seen, "DUPLICATE_ARCHIVE_MEMBER")
                require(len(seen) < MAX_MEMBERS, "TOO_MANY_ARCHIVE_ENTRIES")
                require(item.isfile() or item.isdir() or item.issym(),
                        "NON_REGULAR_ARCHIVE_MEMBER")
                require(not (item.mode & 0o6000), "SETUID_OR_SETGID_ARCHIVE_MEMBER")
                if item.issym():
                    require(in_html(path), "SYMLINK_OUTSIDE_HTML")
                    links[path] = item.linkname
                seen.add(path)
                if item.isfile():
                    regular_files += 1
                    total_content_bytes += item.size
                elif item.isdir():
                    directories += 1
                if path == "BACKUP-MANIFEST.txt":
                    require(item.isfile() and item.size < 4096, "INVALID_MANIFEST")
                    manifest_member = item
                if path == "nextcloud.sql.gz":
                    require(item.isfile(), "INVALID_SQL_MEMBER")
                    sql_member = item
            required = {
                "html", "html/config", "html/config/config.php",
                "html/data", "html/occ", "nextcloud.sql.gz",
                "BACKUP-MANIFEST.txt",
            }
            require(required.issubset(seen), "REQUIRED_NEXTCLOUD_MEMBERS_MISSING")
            validate_symbolic_links(seen, links)
            require(manifest_member is not None and sql_member is not None,
                    "REQUIRED_METADATA_MISSING")

            source = tar.extractfile(manifest_member)
            require(source is not None, "MANIFEST_UNREADABLE")
            manifest = source.read(4096).decode("utf-8", "strict")
            require("format=bergen-nextcloud-v1\n" in manifest,
                    "MANIFEST_FORMAT_UNEXPECTED")
            require("database=nextcloud\n" in manifest,
                    "MANIFEST_DATABASE_UNEXPECTED")
            require("snapshot_utc=" + ident + "\n" in manifest,
                    "MANIFEST_SNAPSHOT_MISMATCH")

            wrapped = tar.extractfile(sql_member)
            require(wrapped is not None, "SQL_UNREADABLE")
            sql_size = 0
            prefix = bytearray()
            with gzip.GzipFile(fileobj=wrapped, mode="rb") as sql:
                while True:
                    chunk = sql.read(1024 * 1024)
                    if not chunk:
                        break
                    sql_size += len(chunk)
                    require(sql_size <= MAX_SQL_BYTES, "SQL_UNCOMPRESSED_TOO_LARGE")
                    if len(prefix) < 262144:
                        prefix.extend(chunk[:262144-len(prefix)])
            require(sql_size > 1024, "SQL_DUMP_EMPTY")
            require(re.search(rb"(?im)^\s*USE\s+[\x60]?nextcloud[\x60]?\s*;",
                              prefix) is not None, "SQL_DATABASE_NOT_CONFIRMED")
    except (tarfile.TarError, gzip.BadGzipFile, EOFError, OSError, UnicodeError) as exc:
        raise AuditError("CORRUPT_ARCHIVE_OR_METADATA") from exc
    return {
        "snapshot_id": ident,
        "sha256_verified": True,
        "tar_catalog_safe": True,
        "regular_file_count": regular_files,
        "directory_count": directories,
        "verified_symbolic_link_count": len(links),
        "all_link_chains_within_html": True,
        "total_uncompressed_content_bytes": total_content_bytes,
        "sql_gzip_valid": True,
        "sql_uncompressed_bytes": sql_size,
        "config_present": True,
        "data_directory_present": True,
        "manifest_valid": True,
        "archive_extracted": False,
        "guest_started": False,
        "database_imported": False,
    }


def main():
    if len(sys.argv) != 3:
        raise AuditError("EXPECTED_ID_AND_DIGEST")
    ident, digest = sys.argv[1:]
    require(socket.gethostname().split(".")[0] == "venombox",
            "WRONG_HOST")
    require(ROOT.is_dir() and not ROOT.is_symlink(),
            "UNEXPECTED_RESTORE_WORKSPACE")
    root_stat = ROOT.stat()
    require(root_stat.st_uid == 0 and stat.S_IMODE(root_stat.st_mode) == 0o700,
            "WORKSPACE_PERMISSIONS_UNSAFE")
    archive = ROOT / ("nextcloud-" + ident + ".tar.gz")
    require(archive.parent == ROOT, "UNSAFE_ARCHIVE_LOCATION")
    report = inspect(archive, ident, digest)
    print(json.dumps(report, sort_keys=True))
    print("NEXTCLOUD_RESTORE_ARCHIVE_AUDIT=PASS")


if __name__ == "__main__":
    try:
        main()
    except AuditError as exc:
        print("NEXTCLOUD_RESTORE_ARCHIVE_AUDIT_FAILED=" + str(exc))
        sys.exit(2)
