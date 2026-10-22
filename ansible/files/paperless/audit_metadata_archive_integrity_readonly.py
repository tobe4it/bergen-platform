"""Read-only integrity preflight for the newest CT126 LXC vzdump archive.

Bounded to one matching local NFS archive selected from a verified mount.
Streams the file to SHA256 and runs zstd+tar checks without extracting any
content. Does not inspect actual private paths or emit archived filenames.
Neither an archive pass nor SHA256 proves recoverability or DB integrity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

FRAME = "BERGEN_PAPERLESS_METADATA_ARCHIVE_INTEGRITY_V1:"
MOUNT = Path("/mnt/pve/bergen-synology-backup")
DUMP = MOUNT / "dump"
PATTERN = re.compile(
    r"vzdump-lxc-126-[0-9]{4}_[0-9]{2}_[0-9]{2}-"
    r"[0-9]{2}_[0-9]{2}_[0-9]{2}\.tar\.zst"
)
MAX_AGE = 48 * 3600
MAX_ARCHIVE_BYTES = 32 * 1024**3
MIN_ARCHIVE_BYTES = 1024**2


class Refuse(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise Refuse(reason)


def read_only_command(argv, timeout_seconds):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=timeout_seconds, check=False)
    require(result.returncode == 0, "ARCHIVE_FORMAT_CHECK_FAILED")


def mounted_backup():
    p = subprocess.run(
        ["findmnt", "--mountpoint", str(MOUNT), "-n", "-o", "FSTYPE"],
        capture_output=True, text=True, timeout=15, check=False)
    require(p.returncode == 0 and p.stdout.strip() in ("nfs", "nfs4"),
            "NFS_MOUNT_NOT_PROVEN")
    require(DUMP.is_dir() and not DUMP.is_symlink(),
            "DUMP_DIRECTORY_NOT_REVIEWED")


def select_archive(now):
    matches = []
    for item in DUMP.iterdir():
        if PATTERN.fullmatch(item.name) is None or item.is_symlink():
            continue
        info = item.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            continue
        if (MIN_ARCHIVE_BYTES <= info.st_size <= MAX_ARCHIVE_BYTES and
                0 <= now - info.st_mtime <= MAX_AGE):
            matches.append((info.st_mtime_ns, item))
    require(matches, "FRESH_CT126_ARCHIVE_NOT_FOUND")
    latest_time = max(x[0] for x in matches)
    latest = [p for mtime, p in matches if mtime == latest_time]
    require(len(latest) == 1, "NEWEST_ARCHIVE_AMBIGUOUS")
    return latest[0], len(matches)


def full_stream_digest(file_path):
    require(not file_path.is_symlink(), "ARCHIVE_SYMLINK_REJECTED")
    checksum = hashlib.sha256()
    with file_path.open("rb", buffering=1024*1024) as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and
                MIN_ARCHIVE_BYTES <= before.st_size <= MAX_ARCHIVE_BYTES,
                "ARCHIVE_FILE_UNREVIEWED")
        while True:
            block = stream.read(4 * 1024 * 1024)
            if not block:
                break
            checksum.update(block)
        after = os.fstat(stream.fileno())
        require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) ==
                (before.st_dev, before.st_ino, before.st_size,
                 before.st_mtime_ns), "ARCHIVE_CHANGED_DURING_READ")
    return checksum.hexdigest(), before.st_size, before.st_mtime_ns


def emit(status, **values):
    print(FRAME + json.dumps({
        "STATUS": status, "AUDIT": "READ_ONLY", "CHANGED": False,
        "CT126_STATE_CHANGED": "NO",
        "CLONE_CREATED": "NO", "RESTORE_PERFORMED": "NO",
        "NETWORK_ISOLATION_PROVEN": "NO",
        "DATABASE_RECOVERY_PROVEN": "NO",
        **values,
    }, sort_keys=True, separators=(",", ":")), flush=True)


def main():
    try:
        require(os.geteuid() == 0, "ROOT_REQUIRED")
        require(os.uname().nodename.split(".")[0] == "venombox",
                "HOST_NOT_REVIEWED")
        mounted_backup()
        path, count = select_archive(time.time())
        digest, nbytes, original_mtime = full_stream_digest(path)
        # Both commands are strictly read-only. stdout/stderr are not logged:
        # tar entries may include private file names.
        read_only_command(["zstd", "-t", "-q", "--", str(path)], 600)
        read_only_command(["tar", "--zstd", "-t", "-f", str(path)], 600)
        current = path.stat(follow_symlinks=False)
        require((current.st_size, current.st_mtime_ns) ==
                (nbytes, original_mtime),
                "ARCHIVE_CHANGED_DURING_CHECK")
        emit("ARCHIVE_STREAM_AND_TAR_OK",
             RECENT_BACKUP_COUNT=count,
             ARCHIVE_SIZE_MIB=round(nbytes / (1024**2)),
             ARCHIVE_SHA256=digest,
             ZSTD_STREAM="PASSED",
             TAR_DIRECTORY_SCAN="PASSED",
             NEXT_GATE="EXPLICIT_OFFLINE_RESTORE_PLAN_APPROVAL")
    except Refuse as exc:
        emit("BLOCKED", REASON=str(exc))
    except subprocess.TimeoutExpired:
        emit("BLOCKED", REASON="INTEGRITY_CHECK_TIMEOUT")
    except Exception:
        emit("BLOCKED", REASON="UNCLASSIFIED")


main()
