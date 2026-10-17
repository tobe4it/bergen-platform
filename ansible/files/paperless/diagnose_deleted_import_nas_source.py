#!/usr/bin/env python3
"""Targeted read-only diagnosis for a previously verified NAS scan source.

Run as paperless-sync via stdin on Synology. Does not create, modify,
rename, transfer or delete anything. Fail closed on unsafe existing files.
"""
import hashlib
import os
import pwd
import stat
import sys
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path


def diagnose(parent, scope, basename, expected_sender_receipt):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_PARENT")
    if scope != "Privat/thomas" or basename != "Gebuehren 2.pdf":
        raise RuntimeError("UNAPPROVED_DIAGNOSTIC_TARGET")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import (
        metadata, read_receipt, receipt_path, secure_state, signature
    )
    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(SETTINGS["sync_user"]).pw_uid:
        raise RuntimeError("RESTRICTED_SYNC_USER_REQUIRED")
    secure_state()
    matching = [(folder, route) for folder, route in SETTINGS["sources"] if route == scope]
    if len(matching) != 1:
        raise RuntimeError("SCOPE_NOT_CONFIGURED")
    folder = matching[0][0]
    if not stat.S_ISDIR(folder.lstat().st_mode):
        raise RuntimeError("UNSAFE_SOURCE_DIRECTORY")
    source = folder / basename
    receipt_file = receipt_path(scope, basename)
    if receipt_file.name != expected_sender_receipt:
        raise RuntimeError("SENDER_RECEIPT_ID_MISMATCH")
    lock_file = SETTINGS["state"] / "sync.lock"
    lock_stat = lock_file.lstat()
    if (not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.geteuid()
            or lock_stat.st_nlink != 1 or stat.S_IMODE(lock_stat.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SYNC_LOCK")
    fd = os.open(lock_file, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as lock:
        if os.fstat(lock.fileno()).st_ino != lock_stat.st_ino:
            raise RuntimeError("LOCK_REPLACED")
        flock(lock, LOCK_EX | LOCK_NB)
        receipt = read_receipt(receipt_file)
        if receipt is None:
            print("EXPECTED_SENDER_RECEIPT_ABSENT")
        else:
            if receipt.get("scope") != scope or receipt.get("source") != basename:
                raise RuntimeError("SENDER_RECEIPT_TARGET_MISMATCH")
            print("EXPECTED_SENDER_RECEIPT_PRESENT", receipt["status"])
        try:
            before = metadata(source)
        except FileNotFoundError:
            print("NAS_ORIGINAL_ABSENT", scope + "/" + basename)
            print("NO_FILES_CHANGED")
            return
        print("NAS_ORIGINAL_PRESENT", scope + "/" + basename)
        if receipt is None:
            print("NAS_ORIGINAL_NOT_VERIFIED_WITH_RECEIPT")
            print("NO_FILES_CHANGED")
            return
        digest = receipt.get("sha256")
        if (receipt["status"] != "SENT"
                or not isinstance(digest, str)
                or len(digest) != 64
                or receipt.get("signature") != signature(before)):
            print("NAS_ORIGINAL_RECEIPT_SIGNATURE_OR_STATUS_MISMATCH")
            print("NO_FILES_CHANGED")
            return
        file_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        sha = hashlib.sha256()
        try:
            if signature(os.fstat(file_fd)) != signature(before):
                raise RuntimeError("SOURCE_CHANGED_BEFORE_HASH")
            with os.fdopen(file_fd, "rb") as stream:
                file_fd = -1
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(block)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
        if signature(metadata(source)) != signature(before):
            raise RuntimeError("SOURCE_CHANGED_AFTER_HASH")
        print("NAS_ORIGINAL_SHA256", "MATCH" if sha.hexdigest() == digest else "MISMATCH")
        print("NO_FILES_CHANGED")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("usage: ... STATE_PARENT SCOPE BASENAME SENDER_RECEIPT")
    diagnose(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4])
