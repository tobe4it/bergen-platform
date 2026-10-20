#!/usr/bin/env python3
"""Read-only full-stream zstd and tar-index checks of one existing CT110 archive.

This verifies compressed bytes and readable TAR structure. It does NOT extract,
write, restore, restart, retry backups, or authorize network/apply operations.
No archive member filenames, source names, commands' stderr, or paths are
emitted. Two full NFS reads can be expensive; the operator runs it once.
"""
import json
import os
import re
import signal
import stat
import subprocess
from pathlib import Path

FRAME = "BERGEN_AI_CT110_ARCHIVE_STREAM_CHECK_V1:"
STORAGE = "bergen-synology-backup"
MOUNT = Path("/mnt/pve") / STORAGE
DUMP = MOUNT / "dump"
PREFIX = STORAGE + ":backup/"
ARCHIVE_RE = re.compile(r"vzdump-lxc-110-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.tar\.zst")
COMMAND_TIMEOUT_SECONDS = 5400
MAX_METADATA_BYTES = 1200000


def metadata_command(argv):
    try:
        p = subprocess.run(
            argv, capture_output=True, timeout=25, check=False)
        if p.returncode or len(p.stdout) > MAX_METADATA_BYTES:
            return None
        return json.loads(p.stdout.decode("utf-8", "strict"))
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError):
        return None


def storage_active():
    mount = metadata_command(["findmnt", "-J", "-M", str(MOUNT)])
    fs = mount.get("filesystems") if isinstance(mount, dict) else None
    if not isinstance(fs, list) or len(fs) != 1 or not isinstance(fs[0], dict):
        return False
    if fs[0].get("target") != str(MOUNT) or fs[0].get("fstype") not in ("nfs", "nfs4"):
        return False
    status = metadata_command([
        "pvesh", "get", "/nodes/venombox/storage/" + STORAGE + "/status",
        "--output-format", "json"])
    return bool(isinstance(status, dict) and status.get("active") in (True, 1)
                and "backup" in str(status.get("content", "")).split(","))


def ct110_running():
    try:
        p = subprocess.run(
            ["pct", "status", "110"], check=False,
            capture_output=True, timeout=15)
        return p.returncode == 0 and p.stdout.strip() == b"status: running"
    except (OSError, subprocess.TimeoutExpired):
        return False


def unique_archive_metadata():
    items = metadata_command([
        "pvesh", "get", "/nodes/venombox/storage/" + STORAGE + "/content",
        "--content", "backup", "--output-format", "json"])
    if not isinstance(items, list) or len(items) > 10000:
        return None
    matches = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("volid"), str):
            return None
        if re.search(r"(?:/|:)vzdump-lxc-110-", item["volid"]):
            matches.append(item)
    if len(matches) != 1:
        return None
    item = matches[0]
    volid = item["volid"]
    if not volid.startswith(PREFIX):
        return None
    name = volid[len(PREFIX):]
    if not ARCHIVE_RE.fullmatch(name):
        return None
    size = item.get("size")
    if type(size) is not int or size <= 0:
        return None
    return name, size


def safe_archive(name, metadata_size):
    try:
        mount_stat = MOUNT.lstat()
        dump_stat = DUMP.lstat()
        path = DUMP / name
        f = path.lstat()
        if (not stat.S_ISDIR(mount_stat.st_mode) or
                not stat.S_ISDIR(dump_stat.st_mode) or
                not stat.S_ISREG(f.st_mode) or
                f.st_size != metadata_size):
            return None
        return path, (f.st_dev, f.st_ino, f.st_size, f.st_mtime_ns)
    except OSError:
        return None


def stream_check(argv):
    """One read-only process group, fully terminated on timeout."""
    proc = None
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        return proc.wait(timeout=COMMAND_TIMEOUT_SECONDS) == 0
    except (OSError, subprocess.TimeoutExpired):
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        return False


def stat_unchanged(path, before):
    try:
        after = path.lstat()
        return stat.S_ISREG(after.st_mode) and (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ) == before
    except OSError:
        return False


def fail_result(stage, status):
    return dict(
        STATUS=status,
        VERIFY_STAGE=stage,
        ZSTD_STREAM_CHECK="NOT_COMPLETED",
        TAR_READ_CHECK="NOT_COMPLETED",
        FILE_STABLE_AFTER_CHECK="UNVERIFIED",
        CT110_STATE_AFTER="UNVERIFIED",
    )


def check():
    if not storage_active() or not ct110_running():
        return fail_result("PRECONDITIONS", "REVIEW_REQUIRED")
    archive = unique_archive_metadata()
    if archive is None:
        return fail_result("UNIQUE_ARCHIVE_METADATA", "REVIEW_REQUIRED")
    name, size = archive
    file_info = safe_archive(name, size)
    if file_info is None:
        return fail_result("ARCHIVE_PATH_AND_SIZE", "REVIEW_REQUIRED")
    path, before = file_info
    if not stream_check(["zstd", "-q", "-t", "--", str(path)]):
        return fail_result("ZSTD_STREAM", "CHECK_FAILED_OR_UNAVAILABLE")
    if not stat_unchanged(path, before):
        return fail_result("ARCHIVE_CHANGED_DURING_ZSTD", "REVIEW_REQUIRED")
    if not stream_check(["tar", "-I", "zstd", "-tf", str(path)]):
        return dict(
            STATUS="CHECK_FAILED_OR_UNAVAILABLE", VERIFY_STAGE="TAR_LIST",
            ZSTD_STREAM_CHECK="PASS",
            TAR_READ_CHECK="FAIL_OR_UNAVAILABLE",
            FILE_STABLE_AFTER_CHECK="UNVERIFIED",
            CT110_STATE_AFTER="UNVERIFIED")
    stable = stat_unchanged(path, before)
    running = ct110_running()
    state = "RUNNING" if running else "NOT_VERIFIED_RUNNING"
    return dict(
        STATUS="COMPRESSED_STREAM_AND_TAR_READABLE" if stable and running
        else "REVIEW_REQUIRED",
        VERIFY_STAGE="FINISHED" if stable and running else "POSTCHECK",
        ZSTD_STREAM_CHECK="PASS", TAR_READ_CHECK="PASS",
        FILE_STABLE_AFTER_CHECK="YES" if stable else "NO",
        CT110_STATE_AFTER=state,
    )


def main():
    try:
        result = check()
    except Exception:
        result = fail_result("UNVERIFIED", "UNVERIFIED")
    frame = dict(
        AUDIT="READ_ONLY", CHANGED=False,
        BACKUP_EXECUTED=False, BACKUP_RETRIED=False,
        ARCHIVE_EXTRACTED=False, ARCHIVE_CONTENTS_EXPORTED=False,
        BACKUP_INTEGRITY="STREAM_AND_TAR_ONLY_NOT_RESTORE_VERIFIED",
        RESTORE_TEST="NOT_ATTESTED", ROLLBACK_CLEARANCE="NOT_PROVEN",
        NETWORK_CHANGES="NONE", APPLY_AUTHORIZED=False,
        **result)
    print(FRAME + json.dumps(frame, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
