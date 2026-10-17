#!/usr/bin/env python3
"""Read-only Synology archive preflight for Bergen Paperless.

No rename, unlink, mkdir, chmod, chown or receipt mutation. The archive
must not be enabled until filename-versioning and acknowledgement logic
are implemented and independently tested.
"""
import hashlib
import json
import os
import pwd
import stat
import sys
from pathlib import Path


def require_directory(path, owner, mode, label):
    try:
        s = path.lstat()
    except FileNotFoundError:
        print("BLOCKER", label, "MISSING")
        return None
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != owner or stat.S_IMODE(s.st_mode) != mode:
        print("BLOCKER", label, "UNSAFE_OWNER_MODE_OR_TYPE")
        return None
    return s


def audit(parent):
    if not parent.is_absolute() or ".." in parent.parts or str(parent) == "/":
        raise RuntimeError("INVALID_PARENT")
    bindir = parent / "bin"
    if not stat.S_ISDIR(bindir.lstat().st_mode):
        raise RuntimeError("INVALID_CODE_DIRECTORY")
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS

    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    user = pwd.getpwnam(SETTINGS["sync_user"])
    if os.geteuid() != user.pw_uid or user.pw_uid == 0:
        raise RuntimeError("RUN_AS_CONFIGURED_SYNC_USER_ONLY")

    archive = parent / "paperless-archive"
    state = SETTINGS["state"]
    blockers = 0
    stats = {"sent": 0, "prepared": 0, "unknown": 0, "untracked": 0,
             "changed": 0, "tracked": 0, "missing": 0}

    def blocker(scope, code):
        nonlocal blockers
        blockers += 1
        print("BLOCKER", scope, code)

    for path, owner, mode, label in (
        (SETTINGS["root"], 0, 0o755, "STATE_ROOT"),
        (parent, 0, 0o755, "STATE_PARENT"),
        (bindir, 0, 0o755, "CODE_DIR"),
        (state, user.pw_uid, 0o700, "SYNC_STATE"),
        (archive, user.pw_uid, 0o700, "ARCHIVE_ROOT"),
    ):
        if require_directory(path, owner, mode, label) is None:
            blockers += 1

    if not state.is_dir():
        print("ARCHIVE_PREFLIGHT_BLOCKED", blockers)
        return

    for folder, scope in SETTINGS["sources"]:
        if not folder.is_dir() or folder.is_symlink():
            blocker(scope, "INVALID_SOURCE_DIRECTORY")
            continue
        dest = archive
        valid = True
        for part in scope.split("/"):
            dest = dest / part
            if require_directory(dest, user.pw_uid, 0o700, scope + "_ARCHIVE") is None:
                blockers += 1
                valid = False
        if valid:
            source_device = folder.stat().st_dev
            archive_device = dest.stat().st_dev
            if source_device != archive_device:
                blocker(scope, "CROSS_DEVICE_RENAME_NOT_ATOMIC")
            else:
                print("SAME_FILESYSTEM", scope)
        print("ACL_REVIEW_REQUIRED", scope, "DSM_DELETE_CHILD_AND_RENAME")
        for path in sorted(folder.iterdir()):
            if path.name.startswith(".") or path.suffix.lower() != ".pdf":
                continue
            if not path.is_file() or path.is_symlink():
                blocker(scope, "UNSAFE_SOURCE_ENTRY")
                continue
            key = hashlib.sha256((scope + "\0" + path.name).encode("utf-8")).hexdigest()
            receipt_path = state / (key + ".json")
            if not receipt_path.exists():
                stats["untracked"] += 1
                continue
            rs = receipt_path.lstat()
            if (not stat.S_ISREG(rs.st_mode) or rs.st_uid != user.pw_uid
                    or rs.st_nlink != 1 or stat.S_IMODE(rs.st_mode) != 0o600):
                blocker(scope, "UNSAFE_RECEIPT")
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                blocker(scope, "UNREADABLE_RECEIPT")
                continue
            if (receipt.get("scope") != scope or receipt.get("source") != path.name):
                blocker(scope, "RECEIPT_SCOPE_OR_NAME_MISMATCH")
                continue
            status = receipt.get("status")
            if status == "SENT":
                stats["sent"] += 1
                signature = [v for v in (path.stat().st_dev, path.stat().st_ino,
                             path.stat().st_size, path.stat().st_mtime_ns,
                             path.stat().st_ctime_ns)]
                if signature == receipt.get("signature"):
                    stats["tracked"] += 1
                else:
                    stats["changed"] += 1
                    blocker(scope, "FILENAME_REUSE_OR_CHANGED_SOURCE")
            elif status == "PREPARED":
                stats["prepared"] += 1
                blocker(scope, "PREPARED_RECEIPT_NEEDS_RECONCILIATION")
            else:
                stats["unknown"] += 1
                blocker(scope, "UNSUPPORTED_RECEIPT_STATE")

    print("SENDER_RECEIPT_COUNTS", json.dumps(stats, sort_keys=True))
    # This prerequisite is intentional. The current sender keys by
    # scope+basename, so archival cannot yet be safely activated.
    blocker("GLOBAL", "FILENAME_VERSIONED_RECEIPTS_NOT_IMPLEMENTED")
    print("ARCHIVE_PREFLIGHT_BLOCKED", blockers)
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: synology_archive_preflight.py STATE_PARENT")
    audit(Path(sys.argv[1]))
