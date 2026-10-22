"""Read-only Proxmox storage/ID plan for a no-network Paperless test restore.

No restore, filesystem writes, bridges, guest starts or data access.
All identities are fixed to the reviewed source CT126 and venombox.
Only inventory counters, disk capacity, exact unreserved candidate ID and
refusal codes are printed; no storage paths, IPs or private backup names.
"""
import json
import math
import os
import re
import subprocess

FRAME = "BERGEN_PAPERLESS_METADATA_CLONE_PLAN_V1:"
SOURCE = 126
PREFERRED_ID = 826
ALTERNATE_IDS = tuple(range(820, 830))
STORAGE = "local-zfs"
MIN_FREE_GIB = 16
MAX_SOURCE_GIB = 1024


class Blocked(Exception):
    pass


def require(value, reason):
    if not value:
        raise Blocked(reason)


def get(args, timeout=15):
    p = subprocess.run(args, capture_output=True, text=True,
                       timeout=timeout, check=False)
    require(p.returncode == 0 and len(p.stdout) < 500000,
            "READ_ONLY_HOST_COMMAND_FAILED")
    return p.stdout


def volume_size_gib(row):
    m = re.search(r"(?:^|,)size=([0-9]+(?:[.][0-9]+)?)([KMGTP])(?:,|$)",
                  row)
    require(m is not None, "SOURCE_VOLUME_SIZE_UNKNOWN")
    multiplier = {"K": 1 / (1024 * 1024), "M": 1 / 1024,
                  "G": 1, "T": 1024, "P": 1024 * 1024}
    value = float(m.group(1)) * multiplier[m.group(2)]
    require(0 < value <= MAX_SOURCE_GIB, "SOURCE_VOLUME_SIZE_UNREVIEWED")
    return value


def source_volumes(config):
    fields = dict(line.split(": ", 1) for line in config.splitlines()
                  if ": " in line)
    require(fields.get("hostname") == "bergen-paperless" and
            fields.get("unprivileged") == "1" and
            "lxc.apparmor.profile: unconfined" not in config,
            "SOURCE_CT_IDENTITY_UNREVIEWED")
    require("rootfs" in fields and "mp0" in fields and
            fields["rootfs"].startswith(STORAGE + ":") and
            fields["mp0"].startswith(STORAGE + ":") and
            re.search(r"(?:^|,)mp=/srv/bergen-paperless(?:,|$)",
                      fields["mp0"]) and
            re.search(r"(?:^|,)backup=1(?:,|$)", fields["mp0"]),
            "SOURCE_VOLUME_LAYOUT_UNREVIEWED")
    require(not any(re.fullmatch(r"mp[1-9][0-9]*", name) or
                    re.fullmatch(r"dev[0-9]+", name) or
                    name in ("hookscript", "features")
                    for name in fields),
            "SOURCE_GUEST_SPECIAL_MOUNTS_UNREVIEWED")
    return volume_size_gib(fields["rootfs"]), volume_size_gib(fields["mp0"])


def storage_available_kib(output):
    matches = [line.split() for line in output.splitlines()
               if line.split() and line.split()[0] == STORAGE]
    require(len(matches) == 1, "STORAGE_ENTRY_MISSING")
    cols = matches[0]
    require(len(cols) >= 7 and cols[1] == "zfspool" and cols[2] == "active",
            "STORAGE_NOT_ACTIVE_ZFS")
    require(cols[5].isdigit(), "STORAGE_AVAILABLE_SIZE_UNREVIEWED")
    return int(cols[5])


def allocated_vmids(resources):
    result = json.loads(resources)
    require(isinstance(result, list), "CLUSTER_INVENTORY_UNREVIEWED")
    vmids = set()
    for item in result:
        require(isinstance(item, dict), "CLUSTER_INVENTORY_UNREVIEWED")
        if item.get("type") in ("lxc", "qemu"):
            vmid = item.get("vmid")
            require(type(vmid) is int and 100 <= vmid <= 999999999,
                    "CLUSTER_VMID_UNREVIEWED")
            require(vmid not in vmids, "CLUSTER_VMIDS_AMBIGUOUS")
            vmids.add(vmid)
    require(SOURCE in vmids, "SOURCE_NOT_PRESENT_IN_CLUSTER")
    return vmids


def plan(config, storage_status, resources):
    root, mount = source_volumes(config)
    used = allocated_vmids(resources)
    remaining = [p for p in (PREFERRED_ID,) + ALTERNATE_IDS
                 if p not in used and p != SOURCE]
    require(remaining, "NO_FREE_ID_IN_REVIEWED_POOL")
    chosen = remaining[0]
    free = storage_available_kib(storage_status) / (1024 * 1024)
    # Conservative *planning* requirement from configured rather than
    # current compressed backup size. The restore is not attempted.
    requirement = max(MIN_FREE_GIB, math.ceil((root + mount) * 1.5))
    require(free >= requirement, "INSUFFICIENT_PLANNING_STORAGE")
    return dict(
        STATUS="READY_FOR_NO_NETWORK_RESTORE_DESIGN",
        CANDIDATE_VMID=chosen,
        VMID_STATE="FREE_AT_AUDIT_NOT_RESERVED",
        VMIDS_IN_REVIEWED_POOL_USED=sum(p in used for p in ALTERNATE_IDS),
        STORAGE=STORAGE,
        STORAGE_FREE_GIB=math.floor(free),
        SOURCE_ROOTFS_CONFIGURED_GIB=math.ceil(root),
        SOURCE_DATA_MOUNT_CONFIGURED_GIB=math.ceil(mount),
        PLANNING_MINIMUM_FREE_GIB=requirement,
        TEST_NET_INTERFACES="NONE_PROPOSED",
        NETWORK_ISOLATION_PROVEN="NO",
        RESTORE_READY="REVIEW_ONLY",
        ARCHIVE_INTEGRITY_VERIFIED="NO",
        CLONE_CREATED="NO",
        CHANGED=False,
    )


def main():
    try:
        require(os.geteuid() == 0, "ROOT_REQUIRED")
        require(os.uname().nodename.split(".")[0] == "venombox",
                "HOST_IDENTITY_UNREVIEWED")
        result = plan(
            get(["pct", "config", str(SOURCE)]),
            get(["pvesm", "status"]),
            get(["pvesh", "get", "/cluster/resources", "--type", "vm",
                 "--output-format", "json"]))
        print(FRAME + json.dumps(result, sort_keys=True,
                                 separators=(",", ":")), flush=True)
    except Blocked as e:
        print(FRAME + json.dumps(dict(
            STATUS="BLOCKED", REASON=str(e), CHANGED=False,
            CLONE_CREATED="NO", NETWORK_ISOLATION_PROVEN="NO",
            ARCHIVE_INTEGRITY_VERIFIED="NO"),
            sort_keys=True, separators=(",", ":")), flush=True)
    except Exception:
        print(FRAME + json.dumps(dict(
            STATUS="BLOCKED", REASON="UNCLASSIFIED", CHANGED=False,
            CLONE_CREATED="NO", NETWORK_ISOLATION_PROVEN="NO",
            ARCHIVE_INTEGRITY_VERIFIED="NO"),
            sort_keys=True, separators=(",", ":")), flush=True)


main()
