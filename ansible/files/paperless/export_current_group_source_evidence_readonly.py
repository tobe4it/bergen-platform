#!/usr/bin/env python3
"""NAS current GROUP source and legacy SENT evidence, read-only, locked.

Unlike the strict archive auditor, this classification permits same-inode
mtime/ctime drift ONLY if the entire PDF still hashes to the original SENT
SHA-256. This is NOT an archive/rename/release authorization.
Output contains private identities and MUST be captured under Ansible no_log.
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

GROUPS = frozenset({"Familie", "Eltern"})
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_SOURCES = 10000


def read_pdf(path, metadata, signature):
    before = metadata(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if signature(os.fstat(fd)) != signature(before):
            raise RuntimeError("SOURCE_CHANGED_BEFORE_READ")
        digest = hashlib.sha256()
        first, tail = b"", b""
        with os.fdopen(fd, "rb", closefd=False) as pdf:
            for part in iter(lambda: pdf.read(1024 * 1024), b""):
                if not first:
                    first = part[:8]
                tail = (tail + part)[-2048:]
                digest.update(part)
        if (signature(os.fstat(fd)) != signature(before)
                or signature(metadata(path)) != signature(before)):
            raise RuntimeError("SOURCE_CHANGED_DURING_READ")
        if not first.startswith(b"%PDF-") or b"%%EOF" not in tail:
            raise RuntimeError("INVALID_GROUP_PDF")
        return signature(before), digest.hexdigest()
    finally:
        os.close(fd)


def classify(sig, saved, hashed, expected):
    if (not isinstance(saved, list) or len(saved) != 5
            or any(type(x) is not int or x < 0 for x in saved)
            or not isinstance(expected, str) or not SHA.fullmatch(expected)
            or hashed != expected):
        raise RuntimeError("UNVERIFIED_SOURCE_RECEIPT")
    if sig == saved:
        return "MATCH"
    if sig[:3] == saved[:3]:
        return "SAME_INODE_METADATA_DRIFT"
    raise RuntimeError("SOURCE_INCARCERATION_MISMATCH")


def collect(parent):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import (
        read_receipt, receipt_path, metadata, signature, secure_state,
    )

    uid = pwd.getpwnam(SETTINGS["sync_user"]).pw_uid
    if uid == 0 or os.geteuid() != uid or SETTINGS["parent"] != parent:
        raise RuntimeError("UNAUTHORIZED_GROUP_EVIDENCE_USER")
    secure_state()
    lock = SETTINGS["state"] / "sync.lock"
    old = lock.lstat()
    if (not stat.S_ISREG(old.st_mode) or old.st_uid != uid
            or old.st_nlink != 1 or stat.S_IMODE(old.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SENDER_LOCK")
    lockfd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(lockfd).st_ino != old.st_ino:
            raise RuntimeError("SENDER_LOCK_CHANGED")
        flock(lockfd, LOCK_EX | LOCK_NB)
        out = []
        for folder, scope in SETTINGS["sources"]:
            if scope not in GROUPS:
                continue
            if not stat.S_ISDIR(folder.lstat().st_mode):
                raise RuntimeError("UNSAFE_GROUP_SOURCE_DIRECTORY")
            for path in sorted(folder.iterdir()):
                if path.name.startswith(".") or path.suffix.lower() != ".pdf":
                    continue
                if len(out) >= MAX_SOURCES:
                    raise RuntimeError("GROUP_SOURCE_LIMIT_EXCEEDED")
                sig, digest = read_pdf(path, metadata, signature)
                receipt = read_receipt(receipt_path(scope, path.name))
                if (not isinstance(receipt, dict)
                        or receipt.get("status") != "SENT"
                        or receipt.get("scope") != scope
                        or receipt.get("source") != path.name):
                    raise RuntimeError("GROUP_RECEIPT_NOT_SENT")
                kind = classify(sig, receipt.get("signature"), digest, receipt.get("sha256"))
                stem = re.sub(r"[^\w. -]", "_", path.stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
                expected_destination = scope + "/" + stem + "--nas-" + digest + ".pdf"
                if receipt.get("destination") != expected_destination:
                    raise RuntimeError("SENDER_DESTINATION_MISMATCH")
                out.append({
                    "receiver_source": expected_destination,
                    "sha256": digest, "classification": kind,
                })
    finally:
        os.close(lockfd)
    return out


def main():
    if len(sys.argv) != 2:
        raise RuntimeError("STATE_PARENT_REQUIRED")
    for item in collect(Path(sys.argv[1])):
        print(json.dumps(item, ensure_ascii=True, sort_keys=True))
    print("NAS_CURRENT_GROUP_EVIDENCE_COMPLETE")
    print("NO_FILES_CHANGED")
    print("ARCHIVE_NOT_AUTHORIZED")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        print("NAS_GROUP_EVIDENCE_BLOCKED", file=sys.stderr)
        sys.exit(1)
