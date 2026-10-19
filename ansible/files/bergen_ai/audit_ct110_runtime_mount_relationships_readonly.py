#!/usr/bin/env python3
"""Read-only CT110 proof: Podman runtime mounts point at LXC rootfs data.

Runs on venombox. No raw mount paths, podman inspect output, model names, or
credentials emitted. Observations DO NOT authorize backup by themselves.
"""
import json
import re
import subprocess

FRAME = "BERGEN_AI_CT110_RUNTIME_MOUNT_PROOF_V1:"
PSEUDO = {"proc", "sysfs", "devpts", "tmpfs", "cgroup", "cgroup2", "mqueue",
          "devtmpfs", "securityfs", "hugetlbfs", "pstore", "bpf", "ramfs",
          "fusectl", "configfs", "tracefs", "debugfs", "autofs", "overlay"}
BLOCK_FS = {"ext4", "xfs", "btrfs", "zfs"}
SOURCE = "/srv/ai/open-webui"
DST = "/app/backend/data"
GRAPH = "/var/lib/containers/storage"
MAX_BYTES = 250000


def guest(argv, max_bytes=MAX_BYTES):
    try:
        p = subprocess.run(["pct", "exec", "110", "--"] + list(argv),
                           check=False, capture_output=True, timeout=18)
        if p.returncode or not p.stdout or len(p.stdout) > max_bytes:
            return None
        return p.stdout.decode("utf-8", "strict")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def guest_json(argv):
    raw = guest(argv)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def flatten(items, depth=0):
    if not isinstance(items, list) or depth > 14:
        raise ValueError("invalid mount tree")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid mount")
        fields = tuple(item.get(k) for k in ("target", "fstype", "source"))
        if not all(isinstance(s, str) and 0 < len(s) <= 1600 for s in fields):
            raise ValueError("invalid mount fields")
        yield fields
        children = item.get("children", [])
        if children:
            yield from flatten(children, depth + 1)


def podman_merged(inspect, info):
    """Require one inspected root Podman container and only one data bind."""
    if not isinstance(inspect, list) or len(inspect) != 1:
        return None
    obj = inspect[0]
    if not isinstance(obj, dict):
        return None
    mounts = obj.get("Mounts")
    if (not isinstance(mounts, list) or len(mounts) != 1 or
            not isinstance(mounts[0], dict)):
        return None
    m = mounts[0]
    if (m.get("Source"), m.get("Destination"), m.get("Type")) != (SOURCE, DST, "bind"):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("store"), dict):
        return None
    if info["store"].get("graphRoot") != GRAPH:
        return None
    driver = obj.get("GraphDriver")
    if not isinstance(driver, dict) or not isinstance(driver.get("Data"), dict):
        return None
    merged = driver["Data"].get("MergedDir")
    if not isinstance(merged, str):
        return None
    if not re.fullmatch(r"/var/lib/containers/storage/overlay/[a-f0-9]{16,128}/merged", merged):
        return None
    return merged


def inode_identity(left, right):
    results = []
    for path in (left, right):
        value = guest(["stat", "-Lc", "%d:%i", path], max_bytes=160)
        if value is None:
            return False
        value = value.strip()
        if not re.fullmatch(r"[0-9]+:[0-9]+", value):
            return False
        results.append(value)
    return results[0] == results[1]


def checked_inode(path):
    """Device/inode read only; never export the numeric values."""
    raw = guest(["stat", "-Lc", "%d:%i", path], max_bytes=160)
    if raw is None:
        return None
    value = raw.strip()
    return value if re.fullmatch(r"[0-9]+:[0-9]+", value) else None


def comparison(left, right):
    if left is None or right is None:
        return "UNVERIFIED"
    return "IDENTICAL" if left == right else "DIFFERENT"


def running_podman_pid(inspect):
    if not isinstance(inspect, list) or len(inspect) != 1:
        return None
    obj = inspect[0]
    if not isinstance(obj, dict):
        return None
    state = obj.get("State")
    if not isinstance(state, dict) or state.get("Running") is not True:
        return None
    pid = state.get("Pid")
    return pid if type(pid) is int and 1 < pid < 2 ** 22 else None


def mounted_bind_characteristics(nodes, merged):
    """Return only shape/fstype/source relationships; never raw mount strings."""
    records = list(flatten(nodes))
    roots = [item for item in records if item[0] == "/"]
    candidates = [item for item in records if item[0] == merged + DST]
    if len(roots) != 1 or len(candidates) != 1:
        return dict(BIND_TARGET="NOT_UNIQUE_OR_MISSING",
                    BIND_FSTYPE_RELATION="UNVERIFIED",
                    BIND_SOURCE_RELATION="UNVERIFIED")
    _, root_type, root_src = roots[0]
    _, bind_type, bind_src = candidates[0]
    return dict(
        BIND_TARGET="EXACT_MERGED_DATA_TARGET",
        BIND_FSTYPE_RELATION="MATCHES_ROOT" if bind_type == root_type
                             else "DIFFERS_FROM_ROOT",
        BIND_SOURCE_RELATION=(
            "MATCHES_ROOT_SOURCE" if (
                bind_src == root_src or bind_src.startswith(root_src + "["))
            else "DIFFERS_FROM_ROOT_SOURCE"),
    )


def identity_details(inspect, nodes, merged):
    """Diagnose host-visible versus process-namespace bind inode identities."""
    source_inode = checked_inode(SOURCE)
    merged_inode = checked_inode(merged + DST)
    pid = running_podman_pid(inspect)
    process_inode = checked_inode("/proc/" + str(pid) + "/root" + DST) if pid else None
    details = dict(
        SOURCE_INODE_READ="AVAILABLE" if source_inode else "UNAVAILABLE",
        MERGED_INODE_READ="AVAILABLE" if merged_inode else "UNAVAILABLE",
        CONTAINER_PID="RUNNING_AND_AVAILABLE" if pid else "UNVERIFIED",
        PROCESS_ROOT_INODE_READ="AVAILABLE" if process_inode else "UNAVAILABLE",
        MERGED_INODE_RELATION=comparison(source_inode, merged_inode),
        PROCESS_ROOT_INODE_RELATION=comparison(source_inode, process_inode),
    )
    details.update(mounted_bind_characteristics(nodes, merged))
    return details


def classify(items, merged, same_inode):
    records = list(flatten(items))
    if not 1 <= len(records) <= 240:
        raise ValueError("unexpected mount count")
    root = [item for item in records if item[0] == "/"]
    if len(root) != 1:
        raise ValueError("missing root")
    root_fstype, root_source = root[0][1], root[0][2]
    if root_fstype not in BLOCK_FS:
        raise ValueError("unreviewed root type")
    lxcfs, overlay, bind, other = 0, 0, 0, 0
    for target, fstype, source in records:
        if target == "/" or fstype in PSEUDO:
            continue
        if (fstype == "fuse.lxcfs" and
                (target.startswith("/proc/") or target.startswith("/sys/"))):
            lxcfs += 1
            continue
        if (merged is not None and target == merged and
                fstype == "fuse.fuse-overlayfs" and
                source in ("fuse-overlayfs", "overlay", "fuse.fuse-overlayfs")):
            overlay += 1
            continue
        if (merged is not None and target == merged + DST and
                fstype == root_fstype and
                (source == root_source or source.startswith(root_source + "[")) and
                same_inode):
            bind += 1
            continue
        other += 1
    return dict(LXCFS_SYSTEM_MOUNT_COUNT=lxcfs,
                FUSE_OVERLAY_MOUNT_COUNT=overlay,
                WEBUI_ROOTFS_BIND_MOUNT_COUNT=bind,
                UNACCOUNTED_NONPSEUDO_MOUNT_COUNT=other,
                RUNTIME_MOUNTS_MATCH_EXPECTATION=bool(
                    lxcfs == 10 and overlay == 1 and bind == 1 and other == 0),
                ROOT_FSTYPE_REVIEWED=True)


def report():
    tree = guest_json(["findmnt", "-J", "-o", "TARGET,FSTYPE,SOURCE"])
    if not isinstance(tree, dict):
        raise ValueError("unreadable mounts")
    info = guest_json(["podman", "info", "--format", "json"])
    inspect = guest_json(["podman", "inspect", "open-webui"])
    merged = podman_merged(inspect, info)
    if merged is None:
        return dict(STATUS="REVIEW_REQUIRED", PODMAN_INSPECT_RELATIONSHIP="UNVERIFIED",
                    ROOTFS_BIND_INODE_IDENTITY="UNVERIFIED",
                    LXCFS_SYSTEM_MOUNT_COUNT="UNVERIFIED",
                    FUSE_OVERLAY_MOUNT_COUNT="UNVERIFIED",
                    WEBUI_ROOTFS_BIND_MOUNT_COUNT="UNVERIFIED",
                    UNACCOUNTED_NONPSEUDO_MOUNT_COUNT="UNVERIFIED",
                    RUNTIME_MOUNTS_MATCH_EXPECTATION=False)
    same_inode = inode_identity(SOURCE, merged + DST)
    detail = classify(tree.get("filesystems"), merged, same_inode)
    detail["STATUS"] = ("EXPECTED_RUNTIME_MOUNTS_ONLY"
                        if detail["RUNTIME_MOUNTS_MATCH_EXPECTATION"]
                        else "REVIEW_REQUIRED")
    detail["PODMAN_INSPECT_RELATIONSHIP"] = "EXACT_SINGLE_WEBUI_BIND"
    detail["ROOTFS_BIND_INODE_IDENTITY"] = "IDENTICAL" if same_inode else "UNVERIFIED"
    # Diagnostics never authorize backup; independently identify why the
    # host-visible bind inode comparison failed, including namespace mismatch.
    detail.update(identity_details(inspect, tree.get("filesystems"), merged))
    return detail


def main():
    try:
        detail = report()
    except Exception:
        detail = dict(STATUS="UNVERIFIED", PODMAN_INSPECT_RELATIONSHIP="UNVERIFIED",
                      ROOTFS_BIND_INODE_IDENTITY="UNVERIFIED",
                      LXCFS_SYSTEM_MOUNT_COUNT="UNVERIFIED",
                      FUSE_OVERLAY_MOUNT_COUNT="UNVERIFIED",
                      WEBUI_ROOTFS_BIND_MOUNT_COUNT="UNVERIFIED",
                      UNACCOUNTED_NONPSEUDO_MOUNT_COUNT="UNVERIFIED",
                      RUNTIME_MOUNTS_MATCH_EXPECTATION=False)
    base = dict(AUDIT="READ_ONLY", CHANGED=False, BACKUP_EXECUTED=False,
                BACKUP_AUTHORIZED=False, APPLY_AUTHORIZED=False,
                DATA_INTEGRITY_PROVEN=False, RESTORE_TEST="NOT_ATTESTED",
                ROLLBACK_CLEARANCE="NOT_PROVEN")
    print(FRAME + json.dumps(dict(base, **detail), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
