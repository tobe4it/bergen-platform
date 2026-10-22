"""Read-only feasibility audit of an isolated Paperless metadata test clone.

Never creates guests, extracts backups, changes networking or reads paper files.
No backup name/path, CT ID other than the reviewed source 126, user identity,
document content, secrets or host addresses are printed.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

FRAME = "BERGEN_PAPERLESS_ISOLATED_TEST_READINESS_V1:"
BACKUP_DIR = Path("/mnt/pve/bergen-synology-backup/dump")
BACKUP_ROOT = "/mnt/pve/bergen-synology-backup"
BACKUP_NAME = re.compile(
    r"^vzdump-lxc-126-[0-9]{4}_[0-9]{2}_[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2}\.tar\.zst$"
)


class Blocked(Exception):
    pass


def require(flag, code):
    if not flag:
        raise Blocked(code)


def cmd(args):
    p = subprocess.run(args, capture_output=True, text=True,
                       timeout=12, check=False)
    require(p.returncode == 0, "READ_ONLY_HOST_COMMAND_FAILED")
    return p.stdout


def output(status, **details):
    print(FRAME + json.dumps({
        "STATUS": status,
        "AUDIT": "READ_ONLY",
        "CHANGED": False,
        "CLONE_CREATED": "NO",
        "RESTORE_TESTED": "NO",
        "NETWORK_ISOLATION_PROVEN": "NO",
        "POSTGRES_INTEGRATION_TESTED": "NO",
        **details,
    }, sort_keys=True, separators=(",", ":")), flush=True)


def main():
    try:
        require(os.geteuid() == 0, "ROOT_REQUIRED")
        require(os.uname().nodename.split(".")[0] == "venombox",
                "WRONG_PROXMOX_NODE")
        config = cmd(["pct", "config", "126"])
        require("hostname: bergen-paperless\n" in config and
                "unprivileged: 1\n" in config and
                "lxc.apparmor.profile: unconfined" not in config and
                re.search(r"^rootfs: local-zfs:", config, re.M) and
                re.search(r"^mp0: local-zfs:.*mp=/srv/bergen-paperless,backup=1(,|$)",
                          config, re.M), "SOURCE_GUEST_NOT_REVIEWED")
        fs = cmd(["findmnt", "--mountpoint", BACKUP_ROOT,
                  "-n", "-o", "FSTYPE"]).strip()
        require(fs in {"nfs", "nfs4"}, "BACKUP_FS_NOT_NFS")
        require(BACKUP_DIR.is_dir() and not BACKUP_DIR.is_symlink(),
                "BACKUP_DIRECTORY_NOT_REVIEWED")
        candidates = []
        now = time.time()
        for file in BACKUP_DIR.iterdir():
            if not BACKUP_NAME.fullmatch(file.name) or file.is_symlink() or not file.is_file():
                continue
            st = file.stat()
            if st.st_size >= 1024 * 1024 and 0 <= now-st.st_mtime <= 48*3600:
                candidates.append((st.st_mtime, st.st_size))
        require(candidates, "RECENT_CT126_BACKUP_NOT_FOUND")
        output("BACKUP_READY_FOR_ISOLATED_RESTORE_REVIEW",
               BACKUP_RECENT="YES", BACKUP_ARCHIVES_RECENT=len(candidates),
               MOST_RECENT_BACKUP_SIZE_MIB=round(max(candidates)[1] / (1024*1024)),
               SOURCE_GUEST="CT126_UNPRIVILEGED",
               BACKUP_INCLUDED_DATA_MOUNT="YES",
               NEXT_GATE="REVIEW_CLONE_ID_STORAGE_NETWORK_AND_RESTORE")
    except Blocked as ex:
        output("BLOCKED", REASON=str(ex))
    except Exception:
        output("BLOCKED", REASON="UNCLASSIFIED")


main()
