#!/usr/bin/env python3
"""Read-only feasibility audit for per-source, same-volume NAS quarantine.

No mkdir, rename, delete or ACL change. Archive directories must be created
only after review of the actual Synology mount and ACL layout.
"""
import os
import pwd
import stat
import sys
from pathlib import Path


def inspect(parent):
    if not parent.is_absolute() or ".." in parent.parts or str(parent) == "/":
        raise RuntimeError("INVALID_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state

    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    user = pwd.getpwnam(SETTINGS["sync_user"])
    if os.geteuid() != user.pw_uid or user.pw_uid == 0:
        raise RuntimeError("RESTRICTED_USER_REQUIRED")
    secure_state()
    for folder, scope in SETTINGS["sources"]:
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("UNSAFE_SOURCE_DIR " + scope)
        candidate = folder / ".paperless-archive"
        print("SCOPE", scope)
        print("SOURCE_DEVICE", info.st_dev)
        print("SOURCE_OWNER", info.st_uid, info.st_gid)
        print("SOURCE_MODE", oct(stat.S_IMODE(info.st_mode)))
        print("SOURCE_CAN_WRITE", os.access(folder, os.W_OK))
        print("SOURCE_CAN_EXECUTE", os.access(folder, os.X_OK))
        try:
            target = candidate.lstat()
        except FileNotFoundError:
            print("ARCHIVE_CANDIDATE", "ABSENT")
            print("SAME_VOLUME", "NOT_YET_VERIFIABLE")
        else:
            print("ARCHIVE_CANDIDATE", "EXISTS")
            print("ARCHIVE_DEVICE", target.st_dev)
            if (not stat.S_ISDIR(target.st_mode)
                    or target.st_uid != user.pw_uid
                    or stat.S_IMODE(target.st_mode) != 0o700):
                print("BLOCKER", scope, "UNSAFE_EXISTING_ARCHIVE")
            elif target.st_dev != info.st_dev:
                print("BLOCKER", scope, "CROSS_DEVICE_ARCHIVE")
            else:
                print("SAME_VOLUME", "CONFIRMED")
        print("DSM_ACL_REVIEW_REQUIRED", scope)
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_synology_same_volume_archive.py STATE_PARENT")
    inspect(Path(sys.argv[1]))
