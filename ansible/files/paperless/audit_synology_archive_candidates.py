#!/usr/bin/env python3
"""Read-only live NAS source and SENT receipt inventory, locked against sender.

Never archives, moves, deletes, transfers, or changes receipt files.
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


def main(parent):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import metadata, signature, receipt_path, read_receipt, secure_state

    if SETTINGS["parent"] != parent:
        raise RuntimeError("CONFIG_PARENT_MISMATCH")
    if os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(SETTINGS["sync_user"]).pw_uid:
        raise RuntimeError("RESTRICTED_SYNC_USER_REQUIRED")
    secure_state()
    lock_path = SETTINGS["state"] / "sync.lock"
    lock_st = lock_path.lstat()
    if (not stat.S_ISREG(lock_st.st_mode) or lock_st.st_nlink != 1
            or lock_st.st_uid != os.geteuid()
            or stat.S_IMODE(lock_st.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SYNC_LOCK")
    lock_fd = os.open(str(lock_path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(lock_fd, "rb") as lock:
        if os.fstat(lock.fileno()).st_ino != lock_st.st_ino:
            raise RuntimeError("LOCK_REPLACED")
        flock(lock, LOCK_EX | LOCK_NB)
        total = 0
        for folder, scope in SETTINGS["sources"]:
            if not stat.S_ISDIR(folder.lstat().st_mode):
                raise RuntimeError("UNSAFE_SOURCE_DIR " + scope)
            for path in sorted(folder.iterdir()):
                if path.name.startswith(".") or path.suffix.lower() != ".pdf":
                    continue
                before = metadata(path)
                receipt_file = receipt_path(scope, path.name)
                receipt = read_receipt(receipt_file)
                if receipt is None or receipt.get("status") != "SENT":
                    raise RuntimeError("SOURCE_NOT_CONFIRMED_SENT " + scope + "/" + path.name)
                actual_signature = signature(before)
                prior_signature = receipt.get("signature")
                if (receipt.get("scope") != scope or receipt.get("source") != path.name
                        or not isinstance(prior_signature, list)
                        or len(prior_signature) != 5
                        or any(type(n) is not int or n < 0 for n in prior_signature)
                        or (prior_signature != actual_signature and not (
                            scope in ("Familie", "Eltern")
                            and prior_signature[:3] == actual_signature[:3]))):
                    raise RuntimeError("SOURCE_RECEIPT_MISMATCH " + scope + "/" + path.name)
                # The original receipt is immutable: metadata drift is only
                # accepted if exact inode+size and full SHA remain identical.
                # Hashing below still checks a stable source under sync.lock.
                digest = receipt.get("sha256")
                destination = receipt.get("destination")
                if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                        or not isinstance(destination, str)):
                    raise RuntimeError("INVALID_SENDER_DIGEST_OR_DESTINATION")
                stem = re.sub(r"[^\w. -]", "_", path.stem, flags=re.UNICODE).strip(" ._-")[:120] or "scan"
                expected = scope + "/" + stem + "--nas-" + digest + ".pdf"
                if destination != expected:
                    raise RuntimeError("INVALID_SENDER_DESTINATION " + scope + "/" + path.name)
                file_fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
                sha = hashlib.sha256()
                try:
                    if signature(os.fstat(file_fd)) != signature(before):
                        raise RuntimeError("SOURCE_CHANGED_BEFORE_HASH")
                    with os.fdopen(file_fd, "rb") as stream:
                        file_fd = -1
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            sha.update(chunk)
                finally:
                    if file_fd >= 0:
                        os.close(file_fd)
                if sha.hexdigest() != digest or signature(metadata(path)) != signature(before):
                    raise RuntimeError("SOURCE_CHANGED_OR_HASH_MISMATCH " + scope + "/" + path.name)
                total += 1
                if total > 10000:
                    raise RuntimeError("INVENTORY_LIMIT_EXCEEDED")
                print(json.dumps({
                    "sender_receipt": receipt_file.name,
                    "scope": scope,
                    "source": path.name,
                    "receiver_source": destination,
                    "sha256": digest,
                }, sort_keys=True, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_synology_archive_candidates.py STATE_PARENT")
    main(Path(sys.argv[1]))
