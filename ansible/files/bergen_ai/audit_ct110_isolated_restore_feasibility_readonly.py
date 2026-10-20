#!/usr/bin/env python3
"""Read-only inventory for an isolated CT110 restore rehearsal.

Never restores, creates, starts, or deletes any guest. VMID 910 is a proposed
candidate, not reserved. Backup archive integrity was proven separately.
Output only allowlisted status classes, not source configs or volume IDs.
"""
import json
import re
import subprocess

FRAME = "BERGEN_AI_CT110_RESTORE_FEASIBILITY_V1:"
HOST = "venombox"
SOURCE_VMID = 110
CANDIDATE_VMID = 910
BACKUP_STORE = "bergen-synology-backup"
ARCHIVE_PATTERN = re.compile(
    r"^bergen-synology-backup:backup/vzdump-lxc-110-"
    r"\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.tar\.zst$")
MAX_OUTPUT = 1000000
GIB = 1024 ** 3


def command(args):
    try:
        proc = subprocess.run(args, capture_output=True, timeout=25, check=False)
        if proc.returncode != 0 or len(proc.stdout) > MAX_OUTPUT:
            return None
        return proc.stdout.decode("utf-8", "strict")
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def json_cmd(args):
    value = command(args)
    try:
        return json.loads(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def source_storage():
    config = command(["pct", "config", str(SOURCE_VMID)])
    if config is None or len(config) > 20000:
        return None
    rows = [line for line in config.splitlines() if line.startswith("rootfs: ")]
    if len(rows) != 1:
        return None
    text = rows[0].split(": ", 1)[1]
    m = re.fullmatch(r"([A-Za-z0-9_-]+):[^,\s]+(?:,[^\r\n]*)?", text)
    size = re.search(r"(?:^|,)size=(\d+)G(?:,|$)", text)
    if m is None or size is None:
        return None
    name = m.group(1)
    amount = int(size.group(1))
    if name != "local-zfs" or not 8 <= amount <= 1024:
        return None
    return name, amount


def candidate_unused():
    resources = json_cmd([
        "pvesh", "get", "/cluster/resources",
        "--type", "vm", "--output-format", "json"])
    index = command(["pct", "list"])
    if not isinstance(resources, list) or len(resources) > 10000 or index is None:
        return "UNVERIFIED"
    for item in resources:
        if not isinstance(item, dict) or type(item.get("vmid")) is not int:
            return "UNVERIFIED"
        if item["vmid"] == CANDIDATE_VMID:
            return "IN_USE"
    if re.search(r"(?m)^\s*910\s", index):
        return "IN_USE"
    return "UNUSED_AT_CHECK_TIME"


def storage_capacity(storage):
    if storage is None:
        return "UNVERIFIED"
    name, size_gib = storage
    obj = json_cmd([
        "pvesh", "get", f"/nodes/{HOST}/storage/{name}/status",
        "--output-format", "json"])
    if not isinstance(obj, dict):
        return "UNVERIFIED"
    if obj.get("active") not in (True, 1):
        return "STORAGE_INACTIVE"
    contents = str(obj.get("content", "")).split(",")
    if "rootdir" not in contents or obj.get("type") != "zfspool":
        return "NOT_ROOTDIR_ZFS_STORAGE"
    avail = obj.get("avail")
    if type(avail) is not int or avail < 0:
        return "UNVERIFIED"
    if avail < (size_gib + 10) * GIB:
        return "INSUFFICIENT_CAPACITY_WITH_BUFFER"
    return "ACTIVE_ROOTDIR_ZFS_WITH_BUFFER"


def archive_metadata():
    obj = json_cmd([
        "pvesh", "get", f"/nodes/{HOST}/storage/{BACKUP_STORE}/content",
        "--content", "backup", "--output-format", "json"])
    if not isinstance(obj, list) or len(obj) > 10000:
        return "UNVERIFIED"
    items = []
    for item in obj:
        if not isinstance(item, dict) or not isinstance(item.get("volid"), str):
            return "UNVERIFIED"
        if re.search(r"(?:/|:)vzdump-lxc-110-", item["volid"]):
            items.append(item)
    if len(items) != 1:
        return "NO_UNIQUE_CT110_ARCHIVE"
    match = items[0]
    if (not ARCHIVE_PATTERN.fullmatch(match["volid"]) or
            type(match.get("size")) is not int or match["size"] <= 0):
        return "ARCHIVE_METADATA_UNEXPECTED"
    return "ONE_NONEMPTY_CT110_ZSTD_ARCHIVE"


def report():
    status110 = command(["pct", "status", str(SOURCE_VMID)])
    source_state = "RUNNING" if status110 is not None and status110.strip() == "status: running" else "UNVERIFIED"
    root = source_storage()
    vmid = candidate_unused()
    target = storage_capacity(root)
    archive = archive_metadata()
    ready = (source_state == "RUNNING" and vmid == "UNUSED_AT_CHECK_TIME"
             and target == "ACTIVE_ROOTDIR_ZFS_WITH_BUFFER"
             and archive == "ONE_NONEMPTY_CT110_ZSTD_ARCHIVE")
    return dict(
        AUDIT="READ_ONLY", CHANGED=False,
        STATUS="RESTORE_ENVIRONMENT_CANDIDATE" if ready else "REVIEW_REQUIRED",
        SOURCE_CT110_STATE=source_state,
        CANDIDATE_VMID=CANDIDATE_VMID,
        CANDIDATE_VMID_STATE=vmid,
        TARGET_STORAGE_CLASS=target,
        CT110_ARCHIVE_METADATA=archive,
        ARCHIVE_STREAM_CHECK="PREVIOUSLY_REPORTED_PASS_NOT_RECHECKED",
        ARCHIVE_CONFIG_SANITIZATION="NOT_PROVEN",
        NETWORK_ISOLATION="NOT_PROVEN",
        RESTORE_EXECUTED=False, RESTORE_AUTHORIZED=False,
        NEW_GUEST_CREATED=False, GUEST_STARTED=False,
        RESTORE_TEST="NOT_ATTESTED",
        ROLLBACK_CLEARANCE="NOT_PROVEN",
        NETWORK_CHANGES="NONE", APPLY_AUTHORIZED=False,
    )


def main():
    try:
        state = report()
    except Exception:
        state = dict(AUDIT="READ_ONLY", CHANGED=False, STATUS="UNVERIFIED",
                     SOURCE_CT110_STATE="UNVERIFIED", CANDIDATE_VMID=CANDIDATE_VMID,
                     CANDIDATE_VMID_STATE="UNVERIFIED",
                     TARGET_STORAGE_CLASS="UNVERIFIED",
                     CT110_ARCHIVE_METADATA="UNVERIFIED",
                     ARCHIVE_STREAM_CHECK="PREVIOUSLY_REPORTED_PASS_NOT_RECHECKED",
                     ARCHIVE_CONFIG_SANITIZATION="NOT_PROVEN",
                     NETWORK_ISOLATION="NOT_PROVEN", RESTORE_EXECUTED=False,
                     RESTORE_AUTHORIZED=False, NEW_GUEST_CREATED=False,
                     GUEST_STARTED=False, RESTORE_TEST="NOT_ATTESTED",
                     ROLLBACK_CLEARANCE="NOT_PROVEN", NETWORK_CHANGES="NONE",
                     APPLY_AUTHORIZED=False)
    print(FRAME + json.dumps(state, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
