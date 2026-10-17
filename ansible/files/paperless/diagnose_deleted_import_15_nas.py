#!/usr/bin/env python3
"""Read-only locked NAS search for the original of missing Paperless document 15.

Receives the verified bridge receiver path and digest via command arguments.
Never assumes a source basename from a normalized receiver filename. No writes.
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
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
RECEIPT_RE = re.compile(r"[0-9a-f]{64}\.json\Z")


def lookup(parent, receiver, digest):
    if (not parent.is_absolute() or ".." in parent.parts or parent == Path("/")
            or not isinstance(receiver, str) or not receiver.startswith(SCOPE + "/")
            or receiver.count("/") != 2 or not DIGEST_RE.fullmatch(digest)
            or not receiver.endswith("--nas-" + digest + ".pdf")):
        raise RuntimeError("INVALID_NAS_LOOKUP_TARGET")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state, receipt_path, read_receipt

    if SETTINGS["parent"] != parent:
        raise RuntimeError("STATE_PARENT_MISMATCH")
    if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(SETTINGS["sync_user"]).pw_uid:
        raise RuntimeError("RESTRICTED_SYNC_USER_REQUIRED")
    secure_state()
    folders = [folder for folder, scope in SETTINGS["sources"] if scope == SCOPE]
    if len(folders) != 1 or not stat.S_ISDIR(folders[0].lstat().st_mode):
        raise RuntimeError("SOURCE_SCOPE_NOT_UNIQUE_OR_UNSAFE")
    lock_path = SETTINGS["state"] / "sync.lock"
    lock_st = lock_path.lstat()
    if (not stat.S_ISREG(lock_st.st_mode) or lock_st.st_uid != os.geteuid()
            or lock_st.st_nlink != 1 or stat.S_IMODE(lock_st.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SENDER_LOCK")
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as lock:
        if os.fstat(lock.fileno()).st_ino != lock_st.st_ino:
            raise RuntimeError("SENDER_LOCK_CHANGED")
        flock(lock, LOCK_EX | LOCK_NB)
        matches = []
        for receipt_file in sorted(SETTINGS["state"].glob("*.json")):
            if not RECEIPT_RE.fullmatch(receipt_file.name):
                raise RuntimeError("UNEXPECTED_SENDER_RECEIPT_FILENAME")
            st = receipt_file.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                    or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600):
                raise RuntimeError("UNSAFE_SENDER_RECEIPT")
            item = read_receipt(receipt_file)
            if item is None:
                raise RuntimeError("SENDER_RECEIPT_DISAPPEARED")
            if item.get("destination") != receiver:
                continue
            matches.append((receipt_file, item))
        if len(matches) != 1:
            raise RuntimeError("SENDER_RECEIPT_MATCH_COUNT_" + str(len(matches)))
        receipt_file, item = matches[0]
        name = item.get("source")
        if (item.get("scope") != SCOPE or item.get("status") != "SENT"
                or item.get("sha256") != digest
                or not isinstance(name, str) or not name.lower().endswith(".pdf")
                or not name or name.startswith(".") or name in (".", "..")
                or "/" in name or "\\" in name or "\0" in name):
            raise RuntimeError("HISTORICAL_SENDER_IDENTITY_MISMATCH")
        if receipt_path(SCOPE, name).name != receipt_file.name:
            raise RuntimeError("SENDER_RECEIPT_KEY_MISMATCH")
        signature = item.get("signature")
        if (not isinstance(signature, list) or len(signature) != 5
                or any(type(x) is not int or x < 0 for x in signature)):
            raise RuntimeError("INVALID_HISTORICAL_SIGNATURE")
        stem = re.sub(r"[^\w. -]", "_", Path(name).stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
        if receiver != SCOPE + "/" + stem + "--nas-" + digest + ".pdf":
            raise RuntimeError("HISTORICAL_DESTINATION_MISMATCH")
        original = folders[0] / name
        try:
            original.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("NAS_ORIGINAL_STILL_PRESENT")
        print(json.dumps({
            "schema_version": 1,
            "sender_receipt": receipt_file.name,
            "scope": SCOPE,
            "source": name,
            "receiver_source": receiver,
            "sha256": digest,
            "sender_status": "SENT",
            "nas_original_absent": True,
        }, sort_keys=True, ensure_ascii=True))
        print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: ... STATE_PARENT RECEIVER_SOURCE SHA256")
    lookup(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
