#!/usr/bin/env python3
"""Bounded read-only classification of CT110 guest mounts for backup review.

Does not display mount targets or sources. No backup authorization, regardless
of observed categories. It mirrors the existing preflight mount-type rule and
explains which mounts it rejects, without changing that rule.
"""
import json
import subprocess

FRAME = "BERGEN_AI_CT110_GUEST_MOUNT_DIAG_V1:"
PSEUDO = {"proc", "sysfs", "devpts", "tmpfs", "cgroup", "cgroup2", "mqueue",
          "devtmpfs", "securityfs", "hugetlbfs", "pstore", "bpf", "ramfs",
          "fusectl", "configfs", "tracefs", "debugfs", "autofs", "overlay"}
LXCFS_TARGETS = {
    "/proc/cpuinfo", "/proc/meminfo", "/proc/stat", "/proc/uptime",
    "/proc/diskstats", "/proc/swaps", "/proc/loadavg",
    "/proc/slabinfo", "/proc/pressure/cpu", "/proc/pressure/io",
    "/proc/pressure/memory", "/sys/devices/system/cpu/online",
}
PVE_ETC_TARGETS = {"/etc/hosts", "/etc/hostname", "/etc/resolv.conf"}
MAX_ITEMS = 240
MAX_JSON = 240000


def read_mounts():
    try:
        process = subprocess.run(
            ["pct", "exec", "110", "--", "findmnt", "-J", "-o",
             "TARGET,FSTYPE,SOURCE"],
            capture_output=True, timeout=15, check=False,
        )
        if process.returncode or not process.stdout or len(process.stdout) > MAX_JSON:
            return None
        data = json.loads(process.stdout.decode("utf-8", "strict"))
        return data.get("filesystems") if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return None


def record_category(target, fstype, source):
    if target == "/":
        return "ROOT"
    if fstype in PSEUDO:
        return "PSEUDO_OR_OVERLAY"
    if target in LXCFS_TARGETS and fstype == "fuse.lxcfs":
        return "LXCFS_SYSTEM_TARGET"
    if target in PVE_ETC_TARGETS:
        return "ETC_IDENTITY_TARGET"
    if target.startswith("/proc/") or target.startswith("/sys/"):
        return "OTHER_PROC_OR_SYS"
    if target.startswith("/dev/"):
        return "OTHER_DEV"
    if target.startswith("/run/"):
        return "OTHER_RUN"
    if target.startswith("/srv/ai/"):
        return "OTHER_AI_DATA"
    if target.startswith("/var/lib/containers/") or target.startswith("/home/"):
        return "OTHER_CONTAINER_STORAGE"
    if target.startswith("/mnt/") or target.startswith("/media/"):
        return "OTHER_MOUNTED_STORAGE"
    return "OTHER_NONPSEUDO_TARGET"


def flatten(nodes, depth=0):
    if depth > 12 or not isinstance(nodes, list):
        raise ValueError("unbounded tree")
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("bad mount")
        target = node.get("target")
        fstype = node.get("fstype")
        source = node.get("source")
        if not all(isinstance(x, str) and 0 < len(x) < 1600
                   for x in (target, fstype, source)):
            raise ValueError("bad mount metadata")
        yield target, fstype, source
        children = node.get("children", [])
        if children:
            yield from flatten(children, depth + 1)


def diagnose(nodes):
    records = list(flatten(nodes))
    if not 1 <= len(records) <= MAX_ITEMS or sum(t == "/" for t, _, _ in records) != 1:
        raise ValueError("incomplete root")
    classified = [record_category(*record) for record in records]
    blockers = [category for (target, fstype, source), category
                in zip(records, classified)
                if target != "/" and fstype not in PSEUDO]
    categories = sorted(set(blockers))
    return dict(
        STATUS="CLASSIFIED_FOR_REVIEW",
        TOTAL_MOUNTS=len(records),
        PREVIOUS_PREFLIGHT_BLOCKER_COUNT=len(blockers),
        BLOCKER_CLASSES=categories if len(categories) <= 12 else ["TOO_MANY_CLASSES"],
        LXCFS_SYSTEM_COUNT=blockers.count("LXCFS_SYSTEM_TARGET"),
        ETC_IDENTITY_COUNT=blockers.count("ETC_IDENTITY_TARGET"),
        OTHER_NONPSEUDO_COUNT=sum(
            x not in ("LXCFS_SYSTEM_TARGET", "ETC_IDENTITY_TARGET") for x in blockers),
        PSEUDO_OR_OVERLAY_COUNT=classified.count("PSEUDO_OR_OVERLAY"),
    )


def main():
    try:
        details = diagnose(read_mounts())
    except Exception:
        details = dict(STATUS="UNVERIFIED", TOTAL_MOUNTS="UNVERIFIED",
                       PREVIOUS_PREFLIGHT_BLOCKER_COUNT="UNVERIFIED",
                       BLOCKER_CLASSES=["UNVERIFIED"], LXCFS_SYSTEM_COUNT="UNVERIFIED",
                       ETC_IDENTITY_COUNT="UNVERIFIED",
                       OTHER_NONPSEUDO_COUNT="UNVERIFIED",
                       PSEUDO_OR_OVERLAY_COUNT="UNVERIFIED")
    result = dict(AUDIT="READ_ONLY", CHANGED=False, BACKUP_STARTED=False,
                  BACKUP_AUTHORIZED=False, APPLY_AUTHORIZED=False,
                  ROLLBACK_CLEARANCE="NOT_PROVEN", NETWORK_CHANGES="NONE", **details)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
