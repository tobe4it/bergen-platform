#!/usr/bin/env python3
"""Conservative preflight for one manually approved CT110 vzdump.

No writes and no service restarts. Only a bounded, sanitized status frame
is exported. This is a point-in-time host/guest check, not a restore proof.
"""
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

FRAME = "BERGEN_AI_CT110_ONEOFF_PREFLIGHT_V1:"
STORAGE = "bergen-synology-backup"
MOUNT = Path("/mnt/pve") / STORAGE
TARGET = "110"
GUEST_NAME = "bergen-ai"
PERSISTENT = "/srv/ai/open-webui"
BACKUP_TYPE = "backup"
PSEUDO = {"proc", "sysfs", "devpts", "tmpfs", "cgroup", "cgroup2", "mqueue",
          "devtmpfs", "securityfs", "hugetlbfs", "pstore", "bpf", "ramfs",
          "fusectl", "configfs", "tracefs", "debugfs", "autofs", "overlay"}


def command(argv, timeout=12, limit=220000):
    try:
        result = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
        if result.returncode or len(result.stdout) > limit:
            return None
        return result.stdout.decode("utf-8", "strict")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def json_object(argv):
    raw = command(argv)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


def exact_fuse_device_mount(entries):
    """Permit only one proven FUSE *device*, never an arbitrary host bind."""
    if len(entries) != 1:
        return False
    try:
        parts = shlex.split(entries[0])
    except ValueError:
        return False
    if len(parts) not in (4, 6):
        return False
    if (parts[0] != "/dev/fuse" or
            "/" + parts[1].lstrip("/") != "/dev/fuse" or
            parts[2] != "none" or
            (len(parts) == 6 and parts[4:] != ["0", "0"])):
        return False
    opts = parts[3].split(",")
    return (len(opts) == len(set(opts)) and "bind" in opts and
            "create=file" in opts and
            all(x in {"bind", "optional", "create=file", "ro"} for x in opts))


def guest_config(raw, status):
    if not raw or not status or status.strip() != "status: running":
        return "UNVERIFIED"
    rows = raw.splitlines()
    if (rows.count(f"hostname: {GUEST_NAME}") != 1
            or rows.count("unprivileged: 1") != 1
            or len([row for row in rows if row.startswith("rootfs: ")]) != 1
            or not any(row.startswith("net0: ") for row in rows)):
        return "UNVERIFIED"
    if any(re.match(r"^mp[0-9]+:\s", row) or
           row.startswith("lxc.mount.auto:")
           for row in rows):
        return "EXTRA_MOUNTS_REQUIRE_REVIEW"
    entries = [row.split(": ", 1)[1] for row in rows
               if row.startswith("lxc.mount.entry: ")]
    if any(row.startswith("lxc.mount.entry:") and
           not row.startswith("lxc.mount.entry: ") for row in rows):
        return "EXTRA_MOUNTS_REQUIRE_REVIEW"
    if entries and not exact_fuse_device_mount(entries):
        return "EXTRA_MOUNTS_REQUIRE_REVIEW"
    if any(row.startswith(("exclude-path:", "lxc.hook.",
                           "lxc.apparmor.profile: unconfined",
                           "lxc.mount:")) for row in rows):
        return "EXCLUSION_OR_UNSAFE_GUEST_CONFIG"
    return "RUNNING_ROOTFS_ONLY"

def persistent_data():
    isdir = command(["pct", "exec", TARGET, "--", "test", "-d", PERSISTENT])
    # Successful test has empty stdout: None means command failure.
    if isdir is None:
        return "UNVERIFIED"
    mounted_at = command(["pct", "exec", TARGET, "--", "findmnt", "-n",
                          "-T", PERSISTENT, "-o", "TARGET"])
    return "IN_GUEST_ROOTFS" if mounted_at and mounted_at.strip() == "/" else "UNVERIFIED"


def guest_mounts():
    raw = command(["pct", "exec", TARGET, "--", "findmnt", "-J",
                   "-o", "TARGET,FSTYPE"], limit=250000)
    if not raw:
        return "UNVERIFIED"
    try:
        data = json.loads(raw)
        filesystems = data.get("filesystems")
        if not isinstance(filesystems, list) or not filesystems or len(filesystems) > 250:
            return "UNVERIFIED"
        if not any(isinstance(node, dict) and node.get("target") == "/" for node in filesystems):
            return "UNVERIFIED"

        def visit(nodes, depth=0):
            if depth > 6:
                return None
            for node in nodes:
                if not isinstance(node, dict):
                    return None
                target = node.get("target")
                fstype = node.get("fstype")
                if not isinstance(target, str) or not isinstance(fstype, str):
                    return None
                if target != "/" and fstype.lower() not in PSEUDO:
                    return False
                children = node.get("children", [])
                if children:
                    if not isinstance(children, list):
                        return None
                    result = visit(children, depth + 1)
                    if result is not True:
                        return result
            return True

        outcome = visit(filesystems)
        return ("NO_EXTERNAL_MOUNTS_DETECTED" if outcome is True else
                "EXTERNAL_OR_UNKNOWN_MOUNT" if outcome is False else "UNVERIFIED")
    except (TypeError, ValueError):
        return "UNVERIFIED"


def nfs_storage():
    obj = json_object(["findmnt", "-J", "-M", str(MOUNT)])
    if obj is None:
        return "UNVERIFIED"
    fs = obj.get("filesystems")
    if not isinstance(fs, list) or len(fs) != 1 or not isinstance(fs[0], dict):
        return "UNVERIFIED"
    if fs[0].get("target") != str(MOUNT) or fs[0].get("fstype") not in ("nfs", "nfs4"):
        return "WRONG_MOUNT"
    pve = json_object(["pvesh", "get", f"/nodes/venombox/storage/{STORAGE}/status",
                       "--output-format", "json"])
    if pve is None or pve.get("active") not in (True, 1):
        return "PVE_STORAGE_UNVERIFIED"
    if BACKUP_TYPE not in str(pve.get("content", "" )).split(","):
        return "PVE_BACKUP_CONTENT_UNVERIFIED"
    try:
        mount_stat = MOUNT.lstat()
        if not stat.S_ISDIR(mount_stat.st_mode) or MOUNT.is_symlink():
            return "WRONG_MOUNT"
        free_bytes = os.statvfs(MOUNT).f_bavail * os.statvfs(MOUNT).f_frsize
        if free_bytes < 25 * 1024 ** 3:
            return "INSUFFICIENT_FREE_SPACE"
    except OSError:
        return "UNVERIFIED"
    return "NFS_ACTIVE_WITH_FREE_SPACE"


def temp_space():
    try:
        path = Path("/var/tmp")
        entry = path.lstat()
        if not stat.S_ISDIR(entry.st_mode) or path.is_symlink() or entry.st_mode & 0o7777 != 0o1777:
            return "UNVERIFIED"
        space = os.statvfs(path)
        return ("LOCAL_TMP_SPACE_OK" if space.f_bavail * space.f_frsize >= 2 * 1024 ** 3
                else "LOCAL_TMP_SPACE_LOW")
    except OSError:
        return "UNVERIFIED"


def existing_target_archives():
    raw = command(["pvesh", "get", f"/nodes/venombox/storage/{STORAGE}/content",
                   "--content", "backup", "--output-format", "json"])
    try:
        items = json.loads(raw) if raw is not None else None
        if not isinstance(items, list) or len(items) > 10000:
            return "UNVERIFIED"
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("volid"), str):
                return "UNVERIFIED"
            # Refuse duplicates of any existing CT110 archive in selected target storage.
            if re.search(r"(?:/|:)vzdump-lxc-110-", item["volid"]):
                return "ALREADY_HAS_ARCHIVE"
        return "NO_CT110_ARCHIVE_ON_SELECTED_STORAGE"
    except (ValueError, TypeError):
        return "UNVERIFIED"


def report():
    identity = guest_config(command(["pct", "config", TARGET]),
                            command(["pct", "status", TARGET], limit=250))
    data = persistent_data() if identity == "RUNNING_ROOTFS_ONLY" else "UNVERIFIED"
    mounts = guest_mounts() if identity == "RUNNING_ROOTFS_ONLY" else "UNVERIFIED"
    nfs = nfs_storage()
    tmp = temp_space()
    prior = existing_target_archives() if nfs == "NFS_ACTIVE_WITH_FREE_SPACE" else "UNVERIFIED"
    ready = (identity == "RUNNING_ROOTFS_ONLY" and data == "IN_GUEST_ROOTFS" and
             mounts == "NO_EXTERNAL_MOUNTS_DETECTED" and
             nfs == "NFS_ACTIVE_WITH_FREE_SPACE" and tmp == "LOCAL_TMP_SPACE_OK" and
             prior == "NO_CT110_ARCHIVE_ON_SELECTED_STORAGE")
    return dict(AUDIT="READ_ONLY", CHANGED=False,
                STATUS="PRECHECK_PASSED" if ready else "REVIEW_REQUIRED",
                CT110_IDENTITY=identity, WEBUI_DATA=data, GUEST_MOUNTS=mounts,
                BACKUP_TARGET=nfs, TEMP_SPACE=tmp, ARCHIVE_STATE=prior,
                SAFE_TO_ATTEMPT_SINGLE_BACKUP=ready,
                SERVICE_INTERRUPTION_POSSIBLE=True,
                BACKUP_INTEGRITY="NOT_TESTED", RESTORE_TEST="NOT_ATTESTED",
                FULL_NETWORK_CLEARANCE="NOT_PROVEN", ROLLBACK_CLEARANCE="NOT_PROVEN",
                BACKUP_EXECUTED=False, APPLY_AUTHORIZED=False)


def main():
    try:
        value = report()
    except Exception:
        value = dict(AUDIT="READ_ONLY", CHANGED=False, STATUS="UNVERIFIED",
                     SAFE_TO_ATTEMPT_SINGLE_BACKUP=False, BACKUP_EXECUTED=False,
                     BACKUP_INTEGRITY="NOT_TESTED", RESTORE_TEST="NOT_ATTESTED",
                     FULL_NETWORK_CLEARANCE="NOT_PROVEN", ROLLBACK_CLEARANCE="NOT_PROVEN",
                     APPLY_AUTHORIZED=False)
    print(FRAME + json.dumps(value, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
