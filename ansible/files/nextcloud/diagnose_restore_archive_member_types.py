#!/usr/bin/env python3
"""Read-only bounded TAR entry-type diagnostic for pinned Nextcloud restore.

Only numeric counts and categorical link-target safety are emitted.
No member names, link names, documents, account data or secrets are printed.
"""
import hashlib
import json
from pathlib import Path
import posixpath
import re
import socket
import stat
import sys
import tarfile

ROOT = Path("/var/lib/vz/nextcloud-restore-test")
MAX_ARCHIVE = 60 * 1024**3
MAX_MEMBERS = 1_000_000


class DiagnosticError(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise DiagnosticError(reason)


def path_ok(raw):
    path = raw.rstrip("/")
    return (
        bool(path) and not path.startswith("/")
        and "\\" not in path and "\x00" not in path
        and all(part not in ("", ".", "..") for part in path.split("/"))
    )


def link_kind(member):
    if not member.issym() and not member.islnk():
        return "not_a_link"
    target = member.linkname
    if not target or target.startswith("/") or "\\" in target or "\x00" in target:
        return "unsafe_absolute_empty_or_platform_path"
    if member.issym():
        effective = posixpath.normpath(
            posixpath.join(posixpath.dirname(member.name), target)
        )
    else:
        effective = posixpath.normpath(target)
    if effective == "html" or effective.startswith("html/"):
        return "inside_html_namespace"
    return "outside_html_namespace"


def read_report(archive, expected_hash):
    checks = {
        "regular_file": 0, "directory": 0,
        "symbolic_link": 0, "hard_link": 0,
        "fifo": 0, "character_device": 0, "block_device": 0,
        "other_special": 0,
    }
    links = {
        "inside_html_namespace": 0,
        "outside_html_namespace": 0,
        "unsafe_absolute_empty_or_platform_path": 0,
    }
    invalid_paths = 0
    non_html_entries = 0
    count = 0
    hashed = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            hashed.update(block)
    require(hashed.hexdigest() == expected_hash, "PINNED_ARCHIVE_HASH_MISMATCH")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                count += 1
                require(count <= MAX_MEMBERS, "ARCHIVE_MEMBER_LIMIT")
                if not path_ok(member.name):
                    invalid_paths += 1
                if member.name.split("/", 1)[0] not in {
                    "html", "nextcloud.sql.gz", "BACKUP-MANIFEST.txt"
                }:
                    non_html_entries += 1
                if member.isfile():
                    checks["regular_file"] += 1
                elif member.isdir():
                    checks["directory"] += 1
                elif member.issym():
                    checks["symbolic_link"] += 1
                    links[link_kind(member)] += 1
                elif member.islnk():
                    checks["hard_link"] += 1
                    links[link_kind(member)] += 1
                elif member.isfifo():
                    checks["fifo"] += 1
                elif member.ischr():
                    checks["character_device"] += 1
                elif member.isblk():
                    checks["block_device"] += 1
                else:
                    checks["other_special"] += 1
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as exc:
        raise DiagnosticError("TAR_SCAN_FAILED") from exc
    return {
        "archive_sha256_matches_pinned": True,
        "member_count": count,
        "entry_types": checks,
        "link_targets": links,
        "invalid_archive_paths": invalid_paths,
        "unexpected_top_level_entries": non_html_entries,
        "diagnostic_only": True,
        "archive_extracted": False,
        "guest_started": False,
        "database_imported": False,
    }


def main():
    require(len(sys.argv) == 3, "EXPECTED_SNAPSHOT_AND_DIGEST")
    snapshot, expected = sys.argv[1:]
    require(re.fullmatch(r"20\d{6}T\d{6}Z-\d+", snapshot), "INVALID_SNAPSHOT_ID")
    require(re.fullmatch(r"[0-9a-f]{64}", expected), "INVALID_DIGEST")
    require(socket.gethostname().split(".")[0] == "venombox", "WRONG_HOST")
    require(ROOT.is_dir() and not ROOT.is_symlink(), "UNSAFE_WORKSPACE")
    st = ROOT.stat()
    require(st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o700,
            "UNSAFE_WORKSPACE_PERMISSIONS")
    archive = ROOT / ("nextcloud-" + snapshot + ".tar.gz")
    require(archive.is_file() and not archive.is_symlink(), "ARCHIVE_MISSING")
    st = archive.stat()
    require(st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o600,
            "ARCHIVE_UNSAFE_PERMISSIONS")
    require(1024 * 1024 < st.st_size < MAX_ARCHIVE, "ARCHIVE_UNEXPECTED_SIZE")
    print(json.dumps(read_report(archive, expected), sort_keys=True))
    print("NEXTCLOUD_ARCHIVE_TYPE_DIAGNOSTIC=COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except DiagnosticError as exc:
        print("NEXTCLOUD_ARCHIVE_TYPE_DIAGNOSTIC_FAILED=" + str(exc))
        sys.exit(2)
