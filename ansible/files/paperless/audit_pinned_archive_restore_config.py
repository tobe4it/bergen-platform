"""Read-only sanity audit of the exact pinned CT126 backup configuration.

Does not restore, boot, allocate, create bridges, change networks or print
raw archived configuration. SHA256 is checked against the separately
verified full-stream archive digest before examining Proxmox metadata.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

FRAME = "BERGEN_PAPERLESS_METADATA_RESTORE_CONFIG_V1:"
MOUNT = Path("/mnt/pve/bergen-synology-backup")
DUMP = MOUNT / "dump"
STORAGE_ID = "bergen-synology-backup"
EXPECTED_SHA = "7f0ad64c2c7bc3bdca53be5766fbabc62feadd74025e811e52712e78b8bee24f"
NAME = re.compile(r"vzdump-lxc-126-[0-9]{4}_[0-9]{2}_[0-9]{2}-"
                  r"[0-9]{2}_[0-9]{2}_[0-9]{2}\.tar\.zst")
ROOTFS = re.compile(r"^local-zfs:[^,\n]+(?:,|$)")
MP0 = re.compile(
    r"^local-zfs:[^,\n]+,mp=/srv/bergen-paperless,backup=1(?:,|$)"
)


class Refuse(Exception):
    pass


def require(ok, code):
    if not ok:
        raise Refuse(code)


def command(args, timeout=60):
    p = subprocess.run(args, capture_output=True, text=True,
                       timeout=timeout, check=False)
    require(p.returncode == 0 and len(p.stdout) <= 32000,
            "PVE_READ_ONLY_INSPECTION_FAILED")
    return p.stdout.strip()


def select_exact_backup():
    require(command(["findmnt", "--mountpoint", str(MOUNT),
                     "-n", "-o", "FSTYPE"]) in ("nfs", "nfs4"),
            "BACKUP_NFS_NOT_ACTIVE")
    require(DUMP.is_dir() and not DUMP.is_symlink(),
            "BACKUP_DIRECTORY_UNREVIEWED")
    candidates = []
    now = time.time()
    for f in DUMP.iterdir():
        if not NAME.fullmatch(f.name) or f.is_symlink():
            continue
        st = f.stat(follow_symlinks=False)
        if (stat.S_ISREG(st.st_mode) and
                1024**2 <= st.st_size <= 32*1024**3 and
                0 <= now-st.st_mtime <= 48*3600):
            candidates.append((st.st_mtime_ns, f))
    require(candidates, "NO_RECENT_BACKUP")
    latest_mtime = max(x[0] for x in candidates)
    matches = [f for t, f in candidates if t == latest_mtime]
    require(len(matches) == 1, "BACKUP_ARCHIVE_AMBIGUOUS")
    return matches[0]


def verify_sha(path):
    h = hashlib.sha256()
    with path.open("rb", buffering=1024*1024) as io:
        before = os.fstat(io.fileno())
        require(stat.S_ISREG(before.st_mode), "BACKUP_OBJECT_NOT_FILE")
        while True:
            block = io.read(4*1024*1024)
            if not block:
                break
            h.update(block)
        after = os.fstat(io.fileno())
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) ==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),
                "BACKUP_CHANGED_DURING_SHA")
    require(h.hexdigest() == EXPECTED_SHA, "ARCHIVE_FINGERPRINT_DRIFT")
    return before.st_size, before.st_mtime_ns


def sanitized_config(raw):
    require(0 < len(raw) <= 16000, "ARCHIVED_CONFIG_UNREVIEWED")
    rows = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        require(": " in line, "ARCHIVED_CONFIG_UNREVIEWED")
        key,value = line.split(": ",1)
        require(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]*",key) and
                key not in rows, "ARCHIVED_CONFIG_DUPLICATE_KEY")
        rows[key]=value
    require(rows.get("hostname") == "bergen-paperless" and
            rows.get("unprivileged") == "1" and
            not any(x.startswith("lxc.") for x in rows) and
            rows.get("onboot", "0") in ("0","1"),
            "ARCHIVED_SOURCE_IDENTITY_UNREVIEWED")
    require(ROOTFS.search(rows.get("rootfs","")) is not None and
            MP0.search(rows.get("mp0","")) is not None,
            "ARCHIVED_VOLUME_LAYOUT_UNREVIEWED")
    mounts = [k for k in rows if re.fullmatch(r"mp[0-9]+",k)]
    require(mounts == ["mp0"], "EXTRA_ARCHIVED_MOUNTS_UNREVIEWED")
    require(not any(re.fullmatch(r"dev[0-9]+",k) or
                    k in ("hookscript","startup","lock") for k in rows),
            "ARCHIVED_SPECIAL_FEATURES_UNREVIEWED")
    networks = [k for k in rows if re.fullmatch(r"net[0-9]+",k)]
    require(len(networks) <= 1, "ARCHIVED_NETWORK_LAYOUT_UNREVIEWED")
    return {
        "ARCHIVED_UNPRIVILEGED": "YES",
        "ARCHIVED_ROOTFS_LOCAL_ZFS": "YES",
        "ARCHIVED_DATA_MP0_LOCAL_ZFS_BACKED_UP": "YES",
        "ARCHIVED_NET_INTERFACE_COUNT": len(networks),
        "ARCHIVED_ONBOOT_ENABLED": rows.get("onboot","0") == "1",
        "ARCHIVED_EXTRA_MOUNTS": 0,
        "REQUIRED_RESTORE_OVERRIDE": "NO_NETWORK_NO_ONBOOT_NO_AUTOSTART",
    }


def result(status, **items):
    print(FRAME + json.dumps({
        "STATUS":status, "AUDIT":"READ_ONLY","CHANGED":False,
        "CLONE_CREATED":"NO","RESTORE_PERFORMED":"NO",
        "NETWORK_ISOLATION_PROVEN":"NO",
        "DATABASE_RECOVERY_PROVEN":"NO",**items
    },sort_keys=True,separators=(",",":")),flush=True)


def main():
    try:
        require(os.geteuid() == 0, "ROOT_REQUIRED")
        require(os.uname().nodename.split(".")[0] == "venombox",
                "WRONG_PROXMOX_NODE")
        file = select_exact_backup()
        size,mtime = verify_sha(file)
        volid = STORAGE_ID + ":backup/" + file.name
        path_from_pve = Path(command(["pvesm","path",volid]))
        require(os.path.realpath(str(path_from_pve)) ==
                os.path.realpath(str(file)), "STORAGE_VOLUME_PATH_MISMATCH")
        raw = command(["pvesm","extractconfig",volid], timeout=120)
        sanitized = sanitized_config(raw)
        now = file.stat(follow_symlinks=False)
        require((now.st_size,now.st_mtime_ns) == (size,mtime),
                "BACKUP_CHANGED_DURING_CONFIG_READ")
        # 'pct restore' is intentionally not called. In particular,
        # inheriting net0 or onboot from the archive would be unsafe.
        result("PINNED_ARCHIVE_CONFIG_REVIEWED",
               ARCHIVE_SHA256=EXPECTED_SHA,
               ARCHIVE_SIZE_MIB=round(size/(1024**2)),
               STORAGE_ID=STORAGE_ID,
               NO_NETWORK_RESTORE_CONFIG_REQUIRED="YES",
               **sanitized)
    except Refuse as e:
        result("BLOCKED",REASON=str(e))
    except Exception:
        result("BLOCKED",REASON="UNCLASSIFIED")


main()
