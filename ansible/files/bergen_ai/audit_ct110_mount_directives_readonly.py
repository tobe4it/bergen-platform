#!/usr/bin/env python3
"""Sanitized read-only CT110 mount-directive diagnosis.

Diagnoses *why* the one-off backup preflight saw extra mounts. Does not
authorize any backup: even standard LXC pseudo mounts need live guest checks.
No raw paths, mount sources, container names, user data, or credentials leave
the audited host.
"""
import json
import re
import shlex
import subprocess

FRAME = "BERGEN_AI_CT110_MOUNT_DIAG_V1:"
MAX_CONFIG = 100000
KNOWN_AUTO = {"proc", "sys", "cgroup", "cgroup2"}


def command(argv, limit=MAX_CONFIG):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=12, check=False)
        if result.returncode or len(result.stdout) > limit:
            return None
        return result.stdout.decode("utf-8", "strict")
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def classify_auto(values):
    if not values:
        return "ABSENT"
    if len(values) > 8:
        return "UNVERIFIED"
    for value in values:
        tokens = value.split()
        if not tokens:
            return "UNVERIFIED"
        for token in tokens:
            category = token.split(":", 1)[0]
            if category not in KNOWN_AUTO:
                return "NONSTANDARD_OR_UNKNOWN"
            if not re.fullmatch(r"[A-Za-z0-9_,:+.-]{1,120}", token):
                return "UNVERIFIED"
    return "STANDARD_PSEUDO_DIRECTIVES_PRESENT"


def classify_entry(values):
    if not values:
        return "ABSENT"
    if len(values) > 32:
        return "UNVERIFIED"
    only_devices = True
    for value in values:
        try:
            parts = shlex.split(value)
        except ValueError:
            return "UNVERIFIED"
        if len(parts) < 4:
            return "UNVERIFIED"
        target = "/" + parts[1].lstrip("/")
        if not any(target == prefix or target.startswith(prefix + "/")
                   for prefix in ("/dev", "/proc", "/sys")):
            only_devices = False
    return ("DEVICE_OR_PSEUDO_TARGETS_PRESENT" if only_devices else
            "OTHER_OR_PERSISTENT_TARGETS_PRESENT")


def classify_config(raw):
    if not isinstance(raw, str) or len(raw) > MAX_CONFIG:
        return None
    lines = raw.splitlines()
    if (lines.count("hostname: bergen-ai") != 1 or
            lines.count("unprivileged: 1") != 1 or
            len([line for line in lines if line.startswith("rootfs: ")]) != 1):
        return None
    net0 = any(line.startswith("net0: ") for line in lines)
    if not net0:
        return None
    mp = [line for line in lines if re.match(r"^mp[0-9]+:\s", line)]
    auto = [line.split(": ", 1)[1] for line in lines
            if line.startswith("lxc.mount.auto: ")]
    entries = [line.split(": ", 1)[1] for line in lines
               if line.startswith("lxc.mount.entry: ")]
    hidden = [line for line in lines
              if line.startswith(("lxc.mount:", "lxc.hook.", "exclude-path:"))]
    return dict(CT110_CONFIG_IDENTITY="VERIFIED",
                PVE_MP_DIRECTIVES="PRESENT" if mp else "NONE",
                PVE_MP_COUNT=len(mp),
                LXC_MOUNT_AUTO=classify_auto(auto),
                LXC_MOUNT_AUTO_COUNT=len(auto),
                LXC_MOUNT_ENTRY=classify_entry(entries),
                LXC_MOUNT_ENTRY_COUNT=len(entries),
                OTHER_MOUNT_OR_EXCLUDE_DIRECTIVES=("PRESENT" if hidden else "NONE"))


def dir_and_mount(target):
    # Never print the path or parent mount; return only a classification.
    valid = command(["pct", "exec", "110", "--", "test", "-d", target], limit=10)
    if valid is None:
        return "UNVERIFIED"
    mount = command(["pct", "exec", "110", "--",
                     "findmnt", "-n", "-T", target, "-o", "TARGET"], limit=1000)
    if mount is None:
        return "UNVERIFIED"
    return "GUEST_ROOTFS" if mount.strip() == "/" else "OTHER_GUEST_MOUNT"


def emit(**details):
    result = dict(AUDIT="READ_ONLY", CHANGED=False, STATUS="REVIEW_REQUIRED",
                  BACKUP_EXECUTED=False, BACKUP_AUTHORIZED=False,
                  APPLY_AUTHORIZED=False, ROLLBACK_CLEARANCE="NOT_PROVEN",
                  NETWORK_CHANGES="NONE", BIND_SOURCE_CONTENT="NOT_READ",
                  **details)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


def main():
    try:
        cfg = classify_config(command(["pct", "config", "110"]))
        status = command(["pct", "status", "110"], limit=300)
        if cfg is None or status is None or status.strip() != "status: running":
            emit(CT110_CONFIG_IDENTITY="UNVERIFIED", PVE_MP_DIRECTIVES="UNVERIFIED",
                 LXC_MOUNT_AUTO="UNVERIFIED", LXC_MOUNT_ENTRY="UNVERIFIED",
                 WEBUI_DATA_MOUNT="UNVERIFIED")
            return
        # Probe known data location independently of backup preflight's mount gate.
        data = dir_and_mount("/srv/ai/open-webui")
        emit(**cfg, WEBUI_DATA_MOUNT=data)
    except Exception:
        emit(CT110_CONFIG_IDENTITY="UNVERIFIED", PVE_MP_DIRECTIVES="UNVERIFIED",
             LXC_MOUNT_AUTO="UNVERIFIED", LXC_MOUNT_ENTRY="UNVERIFIED",
             WEBUI_DATA_MOUNT="UNVERIFIED")


if __name__ == "__main__":
    main()
