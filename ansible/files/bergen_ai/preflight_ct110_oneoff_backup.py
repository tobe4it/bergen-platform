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
GRAPHROOT = "/var/lib/containers/storage"
WEBUI_TARGET = "/app/backend/data"
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
    if not exact_fuse_device_mount(entries):
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


def guest_json(argv):
    raw = command(["pct", "exec", TARGET, "--"] + argv, limit=250000)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def guest_stat_inode(path):
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512:
        return None
    raw = command(["pct", "exec", TARGET, "--", "stat", "-Lc",
                   "%d:%i", path], limit=160)
    if raw is None:
        return None
    result = raw.strip()
    return result if re.fullmatch(r"[0-9]+:[0-9]+", result) else None


def flattened_mounts(nodes, depth=0):
    if not isinstance(nodes, list) or depth > 14:
        raise ValueError("invalid mount tree")
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("invalid mount")
        row = tuple(node.get(k) for k in ("target", "fstype", "source"))
        if any(not isinstance(item, str) or not item or len(item) > 1600
               for item in row):
            raise ValueError("invalid mount metadata")
        yield row
        children = node.get("children", [])
        if children:
            yield from flattened_mounts(children, depth + 1)


def inspected_webui_merged(inspect, info):
    if (not isinstance(inspect, list) or len(inspect) != 1 or
            not isinstance(inspect[0], dict)):
        return None
    obj = inspect[0]
    mounts = obj.get("Mounts")
    if (not isinstance(mounts, list) or len(mounts) != 1 or
            not isinstance(mounts[0], dict) or
            (mounts[0].get("Source"), mounts[0].get("Destination"),
             mounts[0].get("Type")) != (PERSISTENT, WEBUI_TARGET, "bind")):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("store"), dict):
        return None
    if info["store"].get("graphRoot") != GRAPHROOT:
        return None
    state = obj.get("State")
    if not isinstance(state, dict) or state.get("Running") is not True:
        return None
    pid = state.get("Pid")
    if type(pid) is not int or not 1 < pid < 2 ** 22:
        return None
    driver = obj.get("GraphDriver")
    data = driver.get("Data") if isinstance(driver, dict) else None
    merged = data.get("MergedDir") if isinstance(data, dict) else None
    if (not isinstance(merged, str) or
            not re.fullmatch(
                r"/var/lib/containers/storage/overlay/[a-f0-9]{16,128}/merged",
                merged)):
        return None
    return merged, pid


def classify_rootfs_runtime_mounts(nodes, merged, root_inode, bind_inode):
    """Accept exactly the known LXCFS + Podman runtime mount fingerprint.

    A non-pseudo source must be from the same guest rootfs dataset and device.
    Never treat generic bind, NFS, other overlay, or autofs as backup-safe.
    """
    records = list(flattened_mounts(nodes))
    if not 1 <= len(records) <= 240:
        return False
    roots = [row for row in records if row[0] == "/"]
    if len(roots) != 1:
        return False
    _, root_type, root_source = roots[0]
    if root_type != "zfs" or not root_source or not root_inode or not bind_inode:
        return False
    # Directories within one rootfs share a device, not the same inode.
    # The separate process-vs-source comparison must match the full pair.
    if root_inode.split(":", 1)[0] != bind_inode.split(":", 1)[0]:
        return False
    if any(len([row for row in records if row[0] == target]) != 0 for target in (
            "/srv/ai/models", "/srv/ai/open-webui",
            GRAPHROOT + "/volumes")):
        return False

    lxcfs = overlay = internal = pseudo = 0
    for target, fstype, source in records:
        if target == "/":
            continue
        if fstype in PSEUDO:
            # Pseudo filesystems are runtime-only, never backed-up app data.
            if fstype in {"overlay", "autofs"} or target.startswith(
                    ("/srv/ai/", GRAPHROOT + "/volumes/")):
                return False
            pseudo += 1
            continue
        if fstype == "fuse.lxcfs":
            if not ((target.startswith("/proc/") or target.startswith("/sys/"))
                    and (source == "lxcfs" or source.startswith("lxcfs["))):
                return False
            lxcfs += 1
            continue
        if (target == merged and fstype == "fuse.fuse-overlayfs" and
                source in ("overlay", "fuse-overlayfs", "fuse.fuse-overlayfs")):
            overlay += 1
            continue
        if (target.startswith(GRAPHROOT + "/") and
                not target.startswith((
                    GRAPHROOT + "/overlay/",
                    GRAPHROOT + "/overlay-containers/",
                    GRAPHROOT + "/volumes/")) and
                fstype == root_type and
                source.startswith(root_source + "[") and source.endswith("]")):
            mount_inode = guest_stat_inode(target)
            if mount_inode is None or (
                    mount_inode.split(":", 1)[0] != root_inode.split(":", 1)[0]):
                return False
            internal += 1
            continue
        return False
    # Live CT110 fingerprint from the read-only 19 Oct audits:
    # 52 mounts = root + 39 pseudo + 10 LXCFS + 1 fuse-overlay + 1 internal bind.
    return (len(records) == 52 and pseudo == 39 and lxcfs == 10
            and overlay == 1 and internal == 1)


def guest_mounts():
    mounts = guest_json(["findmnt", "-J", "-o", "TARGET,FSTYPE,SOURCE"])
    info = guest_json(["podman", "info", "--format", "json"])
    inspect = guest_json(["podman", "inspect", "open-webui"])
    if not isinstance(mounts, dict):
        return "UNVERIFIED"
    identity = inspected_webui_merged(inspect, info)
    if identity is None:
        return "EXTERNAL_OR_UNKNOWN_MOUNT"
    merged, pid = identity
    source_inode = guest_stat_inode(PERSISTENT)
    process_inode = guest_stat_inode("/proc/" + str(pid) + "/root" + WEBUI_TARGET)
    root_inode = guest_stat_inode("/")
    if source_inode is None or source_inode != process_inode or root_inode is None:
        return "EXTERNAL_OR_UNKNOWN_MOUNT"
    try:
        safe = classify_rootfs_runtime_mounts(
            mounts.get("filesystems"), merged, root_inode, source_inode)
        return ("ROOTFS_INTERNAL_RUNTIME_ONLY" if safe else
                "EXTERNAL_OR_UNKNOWN_MOUNT")
    except (ValueError, TypeError, KeyError):
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
             mounts == "ROOTFS_INTERNAL_RUNTIME_ONLY" and
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
