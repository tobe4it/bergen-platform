#!/usr/bin/env python3
"""READ ONLY: classify all NAS v1 receipt/source mismatches, no source names.

The synchronizer's signature includes ctime: an ACL/metadata change can
invalidate it without changing the PDF's content. Never infer a safe receipt
repair, import or archive permission from this diagnosis.

Run through SSH on the Synology as configured unprivileged paperless-sync.
Print only aggregate counts by scope class, never names, digests or file paths.
"""
import hashlib
import os
import pwd
import stat
import sys
from collections import Counter
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

MAX_SOURCES = 10000
MAX_OUTPUT_SCOPES = {"Familie": "GROUP", "Eltern": "GROUP",
                     "Privat/thomas": "PRIVATE",
                     "Privat/nadja": "PRIVATE"}
STATUSES = (
    "MATCH", "MISSING_RECEIPT", "PREPARED_RECEIPT",
    "RECEIPT_IDENTITY_MISMATCH", "METADATA_CTIME_ONLY",
    "METADATA_MTIME_CHANGED", "FILE_INODE_CHANGED",
    "FILE_SIZE_CHANGED", "CONTENT_CHANGED",
    "CONTENT_CHANGED_SAME_STAT", "UNSTABLE_DURING_CHECK",
    "INVALID_RECEIPT",
)


def classify(old, sig, digest):
    """Return the safest applicable single finding for one stable source."""
    if old is None:
        return "MISSING_RECEIPT"
    if old.get("status") == "PREPARED":
        return "PREPARED_RECEIPT"
    if old.get("status") != "SENT":
        return "INVALID_RECEIPT"
    saved = old.get("signature")
    sha = old.get("sha256")
    if (not isinstance(saved, list) or len(saved) != 5
            or any(type(x) is not int or x < 0 for x in saved)
            or not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)):
        return "INVALID_RECEIPT"
    if sha != digest:
        return ("CONTENT_CHANGED_SAME_STAT" if saved == sig
                else "CONTENT_CHANGED")
    if saved == sig:
        return "MATCH"
    if saved[:4] == sig[:4]:
        return "METADATA_CTIME_ONLY"
    if saved[0] != sig[0] or saved[1] != sig[1]:
        return "FILE_INODE_CHANGED"
    if saved[2] != sig[2]:
        return "FILE_SIZE_CHANGED"
    return "METADATA_MTIME_CHANGED"


def hash_locked_file(path, signature, metadata):
    """Hash one stable regular PDF via O_NOFOLLOW, no temporary files."""
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if signature(os.fstat(fd)) != signature(metadata(path)):
            return None
        sha = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(block)
        if (signature(os.fstat(fd)) != signature(metadata(path))):
            return None
        return sha.hexdigest()
    finally:
        os.close(fd)


def main(parent):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import (
        metadata, read_receipt, receipt_path, secure_state, signature,
    )

    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    if (os.geteuid() == 0 or
            os.geteuid() != pwd.getpwnam(SETTINGS["sync_user"]).pw_uid):
        raise RuntimeError("RESTRICTED_USER_REQUIRED")
    secure_state()
    lock_path = SETTINGS["state"] / "sync.lock"
    check = lock_path.lstat()
    if (not stat.S_ISREG(check.st_mode) or check.st_uid != os.geteuid()
            or check.st_nlink != 1 or stat.S_IMODE(check.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SYNC_LOCK")
    fd = os.open(str(lock_path), os.O_RDONLY | os.O_NOFOLLOW)
    counts = Counter()
    total = 0
    try:
        if os.fstat(fd).st_ino != check.st_ino:
            raise RuntimeError("LOCK_REPLACED")
        flock(fd, LOCK_EX | LOCK_NB)
        for folder, scope in SETTINGS["sources"]:
            if scope not in MAX_OUTPUT_SCOPES:
                raise RuntimeError("UNKNOWN_SCOPE")
            if not stat.S_ISDIR(folder.lstat().st_mode):
                raise RuntimeError("UNSAFE_SOURCE_FOLDER")
            group = MAX_OUTPUT_SCOPES[scope]
            for path in sorted(folder.iterdir()):
                if path.name.startswith(".") or path.suffix.lower() != ".pdf":
                    continue
                total += 1
                if total > MAX_SOURCES:
                    raise RuntimeError("SOURCE_LIMIT_EXCEEDED")
                before = metadata(path)
                saved = receipt_path(scope, path.name)
                try:
                    receipt = read_receipt(saved)
                except (ValueError, RuntimeError, OSError):
                    counts[(group, "INVALID_RECEIPT")] += 1
                    continue
                sig = signature(before)
                digest = hash_locked_file(path, signature, metadata)
                if digest is None or signature(metadata(path)) != sig:
                    counts[(group, "UNSTABLE_DURING_CHECK")] += 1
                    continue
                if (receipt is not None and
                        (receipt.get("scope") != scope or
                         receipt.get("source") != path.name)):
                    counts[(group, "RECEIPT_IDENTITY_MISMATCH")] += 1
                    continue
                code = classify(receipt, sig, digest)
                counts[(group, code)] += 1
    finally:
        os.close(fd)

    print("V1_SOURCE_DIAGNOSED " + str(total))
    for group in ("GROUP", "PRIVATE"):
        for code in STATUSES:
            if counts[(group, code)]:
                print("SOURCE_CLASS " + group + " " + code + " " +
                      str(counts[(group, code)]))
    print("NAS_SOURCE_AUDIT_READ_ONLY")
    print("NO_RECEIPTS_CHANGED")
    print("NO_FILES_CHANGED")
    print("NO_ARCHIVE_OR_PURGE")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("V1_DIAGNOSIS_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
    try:
        main(Path(sys.argv[1]))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        print("V1_DIAGNOSIS_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
