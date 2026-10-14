#!/usr/bin/env python3
"""Repair one proven interrupted Synology sender receipt, without touching PDFs.

Dry-run by default. The controlling Ansible playbook must first perform a
fresh live Paperless checksum/owner/ACL audit of the matching IMPORTED receipt.
"""
import argparse
import hashlib
import os
import pwd
import re
import stat
import sys
import time
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

RECEIPT_ID = "66f0963d8a6c97c910be44208ae637b3b5f5dc77ec062ae83dadaa7dd97282f6"
BRIDGE_ID = "f622de2cd7aa2829f6716f09"
DOCUMENT_ID = 23
DIGEST = "f25b05e10b0ea956f8266571538eb2661b3d50017c7a050c580a7cf3addbc6b2"
SCOPE = "Familie"


def verified_source(path, expected_signature):
    from synology_scan_sync import metadata, signature

    before = metadata(path)
    if signature(before) != expected_signature:
        raise RuntimeError("SOURCE_SIGNATURE_CHANGED")
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if signature(os.fstat(fd)) != expected_signature:
            raise RuntimeError("SOURCE_CHANGED_BEFORE_READ")
        sha = hashlib.sha256()
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != DIGEST:
            raise RuntimeError("SOURCE_SHA256_MISMATCH")
        if signature(metadata(path)) != expected_signature:
            raise RuntimeError("SOURCE_CHANGED_DURING_READ")
    finally:
        if fd >= 0:
            os.close(fd)


def main(parent, commit):
    os.umask(0o077)
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import (
        read_receipt, receipt_path, secure_state, write_receipt,
    )

    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(SETTINGS["sync_user"]).pw_uid:
        raise RuntimeError("RUN_AS_RESTRICTED_SYNC_USER_ONLY")
    secure_state()

    lock_path = SETTINGS["state"] / "sync.lock"
    lock_info = lock_path.lstat()
    if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1
            or lock_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SENDER_LOCK")
    fd = os.open(str(lock_path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as lock:
        if os.fstat(lock.fileno()).st_ino != lock_info.st_ino:
            raise RuntimeError("SENDER_LOCK_REPLACED")
        flock(lock, LOCK_EX | LOCK_NB)

        receipt_file = SETTINGS["state"] / (RECEIPT_ID + ".json")
        data = read_receipt(receipt_file)
        if data is None:
            raise RuntimeError("MISSING_PREPARED_RECEIPT")
        name = data.get("source")
        if (not isinstance(name, str) or name in ("", ".", "..")
                or "/" in name or "\x00" in name
                or not name.lower().endswith(".pdf")):
            raise RuntimeError("INVALID_SOURCE_NAME")
        if receipt_path(SCOPE, name) != receipt_file:
            raise RuntimeError("RECEIPT_ID_MISMATCH")
        stem = re.sub(r"[^\w. -]", "_", Path(name).stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
        destination = SCOPE + "/" + stem + "--nas-" + DIGEST + ".pdf"
        if (data.get("scope") != SCOPE or data.get("sha256") != DIGEST
                or data.get("destination") != destination
                or not isinstance(data.get("signature"), list)
                or len(data["signature"]) != 5):
            raise RuntimeError("RECEIPT_CONTENT_MISMATCH")

        folders = [folder for folder, scope in SETTINGS["sources"] if scope == SCOPE]
        if len(folders) != 1:
            raise RuntimeError("SOURCE_SCOPE_NOT_CONFIGURED")
        folder = folders[0]
        if not stat.S_ISDIR(folder.lstat().st_mode):
            raise RuntimeError("UNSAFE_SOURCE_FOLDER")
        verified_source(folder / name, data["signature"])

        if data["status"] == "SENT":
            if (data.get("bridge_receipt") != BRIDGE_ID + ".json"
                    or data.get("document_id") != DOCUMENT_ID
                    or data.get("recovery_reason") != "verified_paperless_import"):
                raise RuntimeError("SENT_NOT_THIS_REPAIR")
            print("ALREADY_REPAIRED", RECEIPT_ID, "document", DOCUMENT_ID)
            return
        if data["status"] != "PREPARED":
            raise RuntimeError("UNEXPECTED_RECEIPT_STATUS")
        if not commit:
            print("DRY_RUN_REPAIR_READY", RECEIPT_ID, "document", DOCUMENT_ID)
            print("NO_FILES_CHANGED")
            return

        updated = dict(data)
        updated.update(
            status="SENT",
            sent_at=time.time(),
            reconciled_at=time.time(),
            manually_confirmed_imported=True,
            bridge_receipt=BRIDGE_ID + ".json",
            document_id=DOCUMENT_ID,
            recovery_reason="verified_paperless_import",
        )
        write_receipt(receipt_file, updated)
        reread = read_receipt(receipt_file)
        if reread != updated:
            raise RuntimeError("REPAIRED_RECEIPT_VERIFICATION_FAILED")
        print("REPAIRED_SENT", RECEIPT_ID, "document", DOCUMENT_ID)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state_parent", type=Path)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    main(args.state_parent, args.commit)
