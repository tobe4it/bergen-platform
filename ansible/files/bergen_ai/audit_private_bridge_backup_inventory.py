#!/usr/bin/env python3
"""Read-only inventory of Proxmox-visible vzdump archives for LXC110/126.

Uses PVE's *local* pvesh API. Archive listings are metadata, not evidence of
data integrity, mount inclusion, restore success, or rollback readiness.
No filenames, storage identifiers, secrets or timestamps leave this script.
"""
import json
import re
import subprocess
import time

FRAME = "BERGEN_AI_BRIDGE_BACKUP_INVENTORY_V1:"
NODE = "venombox"
TARGETS = ("110", "126")
BACKUP_BASENAME = re.compile(
    r"^vzdump-lxc-(110|126)-[0-9]{4}_[0-9]{2}_[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2}\.tar(?:\.(?:zst|gz|lzo))?$"
)
STORAGE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_STORES = 24
MAX_ITEMS_PER_STORE = 5000
MAX_OUTPUT_BYTES = 2000000


def read_json(argv):
    try:
        process = subprocess.run(argv, capture_output=True, check=False, timeout=25)
        if process.returncode or len(process.stdout) > MAX_OUTPUT_BYTES:
            return None
        result = json.loads(process.stdout)
        return result if isinstance(result, list) else None
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, TypeError):
        return None


def backup_id(item):
    if not isinstance(item, dict):
        return None
    volid = item.get("volid")
    if not isinstance(volid, str) or len(volid) > 400:
        return None
    basename = volid.rsplit("/", 1)[-1]
    match = BACKUP_BASENAME.fullmatch(basename)
    if not match:
        return ""
    vmid = match.group(1)
    recorded_id = item.get("vmid")
    if recorded_id is not None and str(recorded_id) != vmid:
        return None
    return vmid


def classify_items(items, now):
    if not isinstance(items, list) or len(items) > MAX_ITEMS_PER_STORE:
        return None
    found = {vmid: set() for vmid in TARGETS}
    for item in items:
        vmid = backup_id(item)
        if vmid is None:
            return None
        if not vmid:
            continue
        ctime = item.get("ctime")
        size = item.get("size")
        if not isinstance(ctime, (int, float)) or not isinstance(size, (int, float)):
            found[vmid].add("PRESENT_AGE_UNVERIFIED")
        elif (ctime > now + 300 or ctime <= 0 or size <= 0):
            found[vmid].add("PRESENT_METADATA_UNVERIFIED")
        elif now - ctime <= 7 * 86400:
            found[vmid].add("RECENT_METADATA")
        else:
            found[vmid].add("OLDER_METADATA")
    return found


def report():
    return dict(AUDIT="READ_ONLY", CHANGED=False, NETWORK_CHANGES="NONE",
                BACKUP_OPERATIONS="NONE", APPLY_AUTHORIZED=False,
                FULL_NETWORK_CLEARANCE="NOT_PROVEN",
                ROLLBACK_CLEARANCE="NOT_PROVEN",
                BACKUP_INTEGRITY="NOT_TESTED", RESTORE_TEST="NOT_ATTESTED",
                MOUNT_COVERAGE="NOT_ATTESTED")


def emit(**fields):
    result = report()
    result.update(fields)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


def execute_inventory():
    raw = read_json(["pvesh", "get", f"/nodes/{NODE}/storage", "--content",
                     "backup", "--output-format", "json"])
    if raw is None or len(raw) > MAX_STORES:
        emit(STATUS="INVENTORY_UNVERIFIED", ACTIVE_BACKUP_STORAGES="UNVERIFIED",
             CT110_BACKUPS="UNVERIFIED", CT126_BACKUPS="UNVERIFIED",
             STORAGE_COVERAGE="INCOMPLETE")
        return
    stores = []
    for item in raw:
        if not isinstance(item, dict):
            emit(STATUS="INVENTORY_UNVERIFIED", ACTIVE_BACKUP_STORAGES="UNVERIFIED",
                 CT110_BACKUPS="UNVERIFIED", CT126_BACKUPS="UNVERIFIED",
                 STORAGE_COVERAGE="INCOMPLETE")
            return
        name = item.get("storage")
        if not isinstance(name, str) or not STORAGE_NAME.fullmatch(name):
            emit(STATUS="INVENTORY_UNVERIFIED", ACTIVE_BACKUP_STORAGES="UNVERIFIED",
                 CT110_BACKUPS="UNVERIFIED", CT126_BACKUPS="UNVERIFIED",
                 STORAGE_COVERAGE="INCOMPLETE")
            return
        # PVE may list inactive backup storages. This is a deliberate gap.
        if item.get("active") in (False, 0, "0"):
            stores.append((name, False))
        else:
            stores.append((name, True))
    now = time.time()
    aggregated = {vmid: set() for vmid in TARGETS}
    incomplete = not bool(stores)
    active = 0
    for store, is_active in stores:
        if not is_active:
            incomplete = True
            continue
        active += 1
        rows = read_json(["pvesh", "get",
                          f"/nodes/{NODE}/storage/{store}/content",
                          "--content", "backup", "--output-format", "json"])
        parsed = classify_items(rows, now)
        if parsed is None:
            incomplete = True
            continue
        for vmid in TARGETS:
            aggregated[vmid].update(parsed[vmid])
    def state(vmid):
        values = aggregated[vmid]
        if "RECENT_METADATA" in values:
            return "RECENT_METADATA_ONLY"
        if "OLDER_METADATA" in values:
            return "OLDER_METADATA_ONLY"
        if values:
            return "PRESENT_METADATA_UNVERIFIED"
        return "UNVERIFIED" if incomplete else "NONE_IN_SCANNED_STORAGES"
    emit(STATUS="INVENTORY_PARTIAL" if incomplete else "VISIBLE_STORAGES_SCANNED",
         ACTIVE_BACKUP_STORAGES=active,
         CT110_BACKUPS=state("110"), CT126_BACKUPS=state("126"),
         STORAGE_COVERAGE="INCOMPLETE" if incomplete else "VISIBLE_ONLY",
         NEXT_ACTION="REVIEW_ARCHIVE_INTEGRITY_MOUNTS_RESTORE_AND_OOB_ACCESS")


if __name__ == "__main__":
    try:
        execute_inventory()
    except Exception:
        emit(STATUS="INVENTORY_UNVERIFIED", ACTIVE_BACKUP_STORAGES="UNVERIFIED",
             CT110_BACKUPS="UNVERIFIED", CT126_BACKUPS="UNVERIFIED",
             STORAGE_COVERAGE="INCOMPLETE")
