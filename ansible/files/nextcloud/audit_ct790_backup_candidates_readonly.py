#!/usr/bin/env python3
"""Inspect scoped CT790 ZFS snapshot and already-mounted NFS vzdump candidates.

No data-file reads, no writes, no archive extraction, no storage activation,
no mount attempts. Candidate existence never certifies backup integrity.
"""
import json
import os
import re
import socket
import stat
import subprocess
import sys
from contextlib import ExitStack

DATASET_RE = re.compile(r"rpool/data/subvol-790-disk-[0-9]+")
BACKUP_RE = re.compile(
    r"vzdump-lxc-790-[0-9]{4}_[0-9]{2}_[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2}"
    r"\.tar\.(?:zst|gz|lzo)"
)
NFS_MOUNT = "/mnt/pve/bergen-synology-backup"
MAX_SNAPSHOTS = 128
MAX_DIR_ENTRIES = 10000
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME

class Refused(Exception):
    pass

def require(condition, message):
    if not condition:
        raise Refused(message)

def exec_readonly(argv):
    require(argv[0] in ("zfs", "findmnt"), "UNAUTHORIZED_EXECUTABLE")
    p = subprocess.run(argv, capture_output=True, text=True, timeout=25, check=False)
    require(len(p.stdout) < 128000 and len(p.stderr) < 2000, "COMMAND_OUTPUT_UNBOUNDED")
    return p

def snapshots(dataset):
    p = exec_readonly([
        "zfs", "list", "-H", "-p", "-r", "-t", "snapshot",
        "-o", "name,creation", dataset
    ])
    require(p.returncode == 0, "ZFS_READ_FAILED")
    lines = p.stdout.splitlines()
    require(len(lines) <= MAX_SNAPSHOTS, "SNAPSHOT_LIST_TOO_LARGE")
    timestamps = []
    for line in lines:
        parts = line.split("\t")
        require(len(parts) == 2 and parts[0].startswith(dataset + "@"),
                "SNAPSHOT_OUT_OF_SCOPE")
        require(parts[1].isdecimal(), "SNAPSHOT_CREATION_INVALID")
        timestamps.append(int(parts[1]))
    return {
        "snapshot_count": len(timestamps),
        "latest_snapshot_epoch": max(timestamps, default=None),
        "snapshot_recovery_proven": False,
    }

def verified_nfs_mount():
    p = exec_readonly([
        "findmnt", "-rn", "--mountpoint", NFS_MOUNT,
        "-o", "FSTYPE,TARGET"
    ])
    if p.returncode != 0:
        return False
    lines = p.stdout.strip().splitlines()
    require(len(lines) == 1, "BACKUP_MOUNT_AMBIGUOUS")
    parts = lines[0].split()
    require(len(parts) == 2, "BACKUP_MOUNT_OUTPUT_INVALID")
    return parts[0] in ("nfs", "nfs4") and parts[1] == NFS_MOUNT

def open_nfs_dumpdir(stack):
    cur = os.open("/", DIR_FLAGS)
    stack.callback(os.close, cur)
    for piece in ("mnt", "pve", "bergen-synology-backup", "dump"):
        try:
            fd = os.open(piece, DIR_FLAGS, dir_fd=cur)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise Refused("BACKUP_DIR_SYMLINK_OR_UNREADABLE") from exc
        stack.callback(os.close, fd)
        require(stat.S_ISDIR(os.fstat(fd).st_mode), "BACKUP_DIR_NOT_DIRECTORY")
        cur = fd
    return cur

def backup_candidates():
    if not verified_nfs_mount():
        return {
            "mount": "NOT_VERIFIED_AS_PREEXISTING_NFS",
            "candidate_count": 0,
            "candidate_bytes_total": 0,
            "latest_candidate_mtime_epoch": None,
            "archive_integrity_proven": False,
            "restore_test_proven": False,
        }
    with ExitStack() as stack:
        dumpfd = open_nfs_dumpdir(stack)
        if dumpfd is None:
            return {
                "mount": "EXISTING_NFS_DUMP_DIR_ABSENT",
                "candidate_count": 0,
                "candidate_bytes_total": 0,
                "latest_candidate_mtime_epoch": None,
                "archive_integrity_proven": False,
                "restore_test_proven": False,
            }
        names = os.listdir(dumpfd)
        require(len(names) <= MAX_DIR_ENTRIES, "BACKUP_DIRECTORY_TOO_LARGE")
        count = 0
        bytes_total = 0
        newest = None
        for name in names:
            if BACKUP_RE.fullmatch(name) is None:
                continue
            st = os.stat(name, dir_fd=dumpfd, follow_symlinks=False)
            require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size > 0,
                    "BACKUP_CANDIDATE_NOT_SAFE_REGULAR_FILE")
            count += 1
            bytes_total += st.st_size
            newest = max(newest or 0, int(st.st_mtime))
        return {
            "mount": "PREEXISTING_NFS_VERIFIED",
            "candidate_count": count,
            "candidate_bytes_total": bytes_total,
            "latest_candidate_mtime_epoch": newest,
            "archive_integrity_proven": False,
            "restore_test_proven": False,
        }

def audit(dataset):
    require(os.geteuid() == 0, "ROOT_REQUIRED")
    require(socket.gethostname().split(".")[0] == "venombox", "HOST_NOT_VENOMBOX")
    require(DATASET_RE.fullmatch(dataset) is not None, "CT790_DATASET_MISMATCH")
    require(hasattr(os, "O_NOATIME"), "NOATIME_NOT_SUPPORTED")
    result = {
        "result": "ROCKY_9_8_CT790_BACKUP_CANDIDATES_READ_ONLY_RECORDED",
        "vmid": 790,
        "snapshot_candidates": snapshots(dataset),
        "scoped_nfs_backup_candidates": backup_candidates(),
        "backup_recoverability_proven": False,
        "sanitation_authorized": False,
        "pct_template_authorized": False,
        "files_written": 0,
        "mount_operations": 0,
        "guest_started": False,
    }
    return result

if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2, "ONE_DATASET_ARGUMENT_REQUIRED")
        print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (Refused, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Refused) else "BOUNDED_READ_FAILED"
        print(json.dumps({
            "result": "ROCKY_9_8_CT790_BACKUP_CANDIDATES_READ_ONLY_BLOCKED",
            "reason": reason,
            "backup_recoverability_proven": False,
            "files_written": 0,
            "mount_operations": 0,
        }, sort_keys=True))
        sys.exit(1)
