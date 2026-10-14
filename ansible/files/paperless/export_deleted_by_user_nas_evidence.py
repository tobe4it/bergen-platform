#!/usr/bin/env python3
"""Read-only locked Synology SENT receipt evidence for an absent original.

Unlike archive candidate inventory, the original PDF is expected to be
absent. Does not create, rename, delete, transfer or modify files.
"""
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

SCOPE = "Privat/thomas"
BASENAME = "Gebuehren 2.pdf"
RECEIPT = "7a9e41ee25d2a98c4e529472f3db2ab6c70b453a3214c1da537175bbcef1b4e8.json"


def main(parent):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_STATE_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state, receipt_path, read_receipt
    if SETTINGS["parent"] != parent:
        raise RuntimeError("STATE_PARENT_MISMATCH")
    if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(SETTINGS["sync_user"]).pw_uid:
        raise RuntimeError("RESTRICTED_SYNC_USER_REQUIRED")
    secure_state()
    matching = [folder for folder, scope in SETTINGS["sources"] if scope == SCOPE]
    if len(matching) != 1:
        raise RuntimeError("SOURCE_SCOPE_NOT_UNIQUE")
    folder = matching[0]
    if not stat.S_ISDIR(folder.lstat().st_mode):
        raise RuntimeError("UNSAFE_SOURCE_DIRECTORY")
    lock_path = SETTINGS["state"] / "sync.lock"
    lock_st = lock_path.lstat()
    if (not stat.S_ISREG(lock_st.st_mode) or lock_st.st_uid != os.geteuid()
            or lock_st.st_nlink != 1 or stat.S_IMODE(lock_st.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SENDER_LOCK")
    lock_fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(lock_fd, "rb") as lock:
        if os.fstat(lock.fileno()).st_ino != lock_st.st_ino:
            raise RuntimeError("SENDER_LOCK_REPLACED")
        flock(lock, LOCK_EX | LOCK_NB)
        path = folder / BASENAME
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("NAS_SOURCE_STILL_PRESENT")
        receipt_file = receipt_path(SCOPE, BASENAME)
        if receipt_file.name != RECEIPT:
            raise RuntimeError("SENDER_RECEIPT_KEY_CHANGED")
        st = receipt_file.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600):
            raise RuntimeError("UNSAFE_SENDER_RECEIPT")
        receipt = read_receipt(receipt_file)
        if (receipt is None or receipt.get("status") != "SENT"
                or receipt.get("scope") != SCOPE
                or receipt.get("source") != BASENAME):
            raise RuntimeError("UNEXPECTED_SENDER_RECEIPT")
        digest = receipt.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError("INVALID_SENDER_DIGEST")
        signature = receipt.get("signature")
        if (not isinstance(signature, list) or len(signature) != 5
                or any(type(item) is not int or item < 0 for item in signature)):
            raise RuntimeError("INVALID_HISTORICAL_SIGNATURE")
        stem = re.sub(r"[^\w. -]", "_", path.stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
        expected_destination = SCOPE + "/" + stem + "--nas-" + digest + ".pdf"
        if receipt.get("destination") != expected_destination:
            raise RuntimeError("SENDER_DESTINATION_MISMATCH")
        print(json.dumps({
            "schema_version": 1,
            "sender_receipt": receipt_file.name,
            "scope": SCOPE,
            "source": BASENAME,
            "receiver_source": expected_destination,
            "sha256": digest,
            "sender_status": "SENT",
            "nas_original_absent": True,
        }, sort_keys=True))
        print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: ... STATE_PARENT")
    main(Path(sys.argv[1]))
