"""Read-only compare before reverting the exact proposed LXC110 GPU stage.

Only the stage's dev0, dev1 and RAM limit may differ from the 0600 recovery
preimage. Never restore the entire Proxmox config over concurrent changes.
"""
import json
from pathlib import Path
import re
import sys

FRAME = "BERGEN_AI_GPU_ROLLBACK_V1:"
BACKUP = Path("/var/lib/bergen-platform-recovery/ollama-gpu/lxc110-pre-gpu.conf")
CURRENT = Path("/etc/pve/lxc/110.conf")


def relevant(text):
    return sorted(line.strip() for line in text.splitlines()
                  if line.strip() and not line.lstrip().startswith("#"))


def main():
    if (not BACKUP.is_file() or BACKUP.is_symlink()
            or not CURRENT.is_file() or CURRENT.is_symlink()):
        raise ValueError("BACKUP_MISSING")
    if BACKUP.stat().st_mode & 0o077:
        raise ValueError("BACKUP_NOT_PRIVATE")
    backup = relevant(BACKUP.read_text())
    current = relevant(CURRENT.read_text())
    if "hostname: bergen-ai" not in backup or "unprivileged: 1" not in backup:
        raise ValueError("UNEXPECTED_IDENTITY")
    if "hostname: bergen-ai" not in current or "unprivileged: 1" not in current:
        raise ValueError("IDENTITY_DRIFT")
    if "memory: 16384" not in backup or "memory: 32768" not in current:
        raise ValueError("MEMORY_DRIFT")
    devs = [line for line in current if re.match(r"^dev[0-9]+:", line)]
    if len(devs) != 2:
        raise ValueError("DEVICE_DRIFT")
    for slot, path in (("dev0", "/dev/dri/renderD128"),
                       ("dev1", "/dev/kfd")):
        candidates = [x for x in devs if x.startswith(slot + ":")]
        if len(candidates) != 1 or path not in candidates[0]:
            raise ValueError("DEVICE_DRIFT")
        if "mode=0660" not in candidates[0]:
            raise ValueError("DEVICE_DRIFT")
    restored = [x for x in current if not x.startswith(("dev0:", "dev1:"))]
    restored[restored.index("memory: 32768")] = "memory: 16384"
    if sorted(restored) != backup:
        raise ValueError("UNRELATED_CONFIG_DRIFT")
    print(FRAME + json.dumps({"AUDIT":"READ_ONLY","CHANGED":False,
                              "STATUS":"EXACT_STAGE_ONLY",
                              "RESTORE_MEMORY_MIB":16384,
                              "DEVICES_TO_REMOVE":["dev0","dev1"]},
                             sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(FRAME + json.dumps({"AUDIT":"READ_ONLY", "CHANGED":False,
                                  "STATUS":"MANUAL_REVIEW_REQUIRED"}))
        sys.exit(2)
