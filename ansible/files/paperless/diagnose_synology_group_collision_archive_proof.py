#!/usr/bin/env python3
"""READ ONLY on NAS, as restricted sync user, under existing sync.lock.

Verify WHETHER each reused GROUP basename has prior complete v1 archive
evidence, without revealing source name, hash, paths, or identity details.
A positive result authorizes no rename and no archival. Source byte changes
or same-inode metadata drift remain blocked pending separate reconciliation.

This must be callable as 'python3 - PARENT' from the controller: it imports
ONLY the already staged/root-pinned v1 sender, archive worker and auditor.
"""
import hashlib
import os
import pwd
import stat
import sys
from collections import Counter
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

GROUPS = frozenset(("Familie", "Eltern"))
LIMIT = 10000


def prior_archive_verified(state, folder, scope, name, receipt, *, move, audit):
    key = hashlib.sha256((scope + "\0" + name).encode("utf-8")).hexdigest()
    journalfd = move._check_dir(state / move.JOURNAL_DIR, os.geteuid())
    try:
        events = audit.inspect_events(
            os.listdir(journalfd),
            lambda entry: audit.read_event(journalfd, entry, os.geteuid()))
    finally:
        os.close(journalfd)
    pair = events.get(key)
    if pair is None:
        return False
    previous = pair["archived"]
    if (previous.get("scope") != scope or previous.get("source") != name
            or previous.get("sender_receipt") != key + ".json"
            or previous.get("sha256") != receipt.get("sha256")
            or previous.get("signature") != receipt.get("signature")
            or previous.get("archive_site") != move.SITE_BY_SCOPE[scope]
            or previous.get("archive_name") != key + ".pdf"):
        return False
    saved = move._read_receipt(state / (key + ".json"),
                               scope, name, previous["signature"], previous["sha256"])
    if saved.get("destination") != receipt.get("destination"):
        return False
    protected = move._validated_protected_scope(folder, scope, os.geteuid())
    if previous.get("archive_scope_dir") != str(protected):
        return False
    monthfd = move._check_dir(protected / previous["archive_month"], os.geteuid())
    try:
        audit.inspect_pdf(monthfd, previous["archive_name"], previous["signature"],
                          previous["sha256"], 512 * 1024 * 1024)
    finally:
        os.close(monthfd)
    return True


def file_digest_unchanged(path, *, metadata, signature):
    before = metadata(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if signature(os.fstat(fd)) != signature(before):
            return None, None
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as pdf:
            for part in iter(lambda: pdf.read(1024 * 1024), b""):
                digest.update(part)
        if (signature(os.fstat(fd)) != signature(before)
                or signature(metadata(path)) != signature(before)):
            return None, None
        return signature(before), digest.hexdigest()
    finally:
        os.close(fd)


def run(parent):
    if not parent.is_absolute() or ".." in parent.parts or parent == Path("/"):
        raise RuntimeError("INVALID_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state, metadata, signature, receipt_path, read_receipt
    import audit_synology_completed_archive_moves as audit
    import synology_same_volume_archive_move as move

    uid = pwd.getpwnam(SETTINGS["sync_user"]).pw_uid
    if (uid == 0 or os.geteuid() != uid or SETTINGS["parent"] != parent
            or set(scope for _folder, scope in SETTINGS["sources"]) !=
               {"Familie", "Eltern", "Privat/thomas", "Privat/nadja"}):
        raise RuntimeError("UNAUTHORIZED_PROBE")
    archive_code = parent / "bin" / "synology_same_volume_archive_move.py"
    archived_code = parent / "bin" / "audit_synology_completed_archive_moves.py"
    for code in (archive_code, archived_code):
        st = code.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_gid != 0
                or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o644):
            raise RuntimeError("UNTRUSTED_STAGED_CODE")
    secure_state()
    lock_path = SETTINGS["state"] / "sync.lock"
    st = lock_path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_nlink != 1
            or stat.S_IMODE(st.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_LOCK")
    lockfd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    counts = Counter()
    try:
        if os.fstat(lockfd).st_ino != st.st_ino:
            raise RuntimeError("REPLACED_LOCK")
        flock(lockfd, LOCK_EX | LOCK_NB)
        total = 0
        for folder, scope in SETTINGS["sources"]:
            if scope not in GROUPS:
                continue
            if not stat.S_ISDIR(folder.lstat().st_mode):
                raise RuntimeError("SOURCE_DIR_INVALID")
            for source in sorted(folder.iterdir()):
                if source.name.startswith(".") or source.suffix.lower() != ".pdf":
                    continue
                total += 1
                if total > LIMIT:
                    raise RuntimeError("TOO_MANY_PDFS")
                actual, digest = file_digest_unchanged(
                    source, metadata=metadata, signature=signature)
                if actual is None:
                    counts["UNSTABLE_SOURCE"] += 1
                    continue
                try:
                    receipt = read_receipt(receipt_path(scope, source.name))
                except (ValueError, RuntimeError, OSError):
                    counts["RECEIPT_INVALID"] += 1
                    continue
                if not isinstance(receipt, dict) or receipt.get("status") != "SENT":
                    counts["NO_SENT_RECEIPT"] += 1
                    continue
                if (receipt.get("scope") != scope or
                        receipt.get("source") != source.name):
                    counts["RECEIPT_INVALID"] += 1
                    continue
                old = receipt.get("signature")
                if (not isinstance(old, list) or len(old) != 5 or
                        any(type(n) is not int or n < 0 for n in old)):
                    counts["RECEIPT_INVALID"] += 1
                    continue
                if old == actual and receipt.get("sha256") == digest:
                    counts["MATCH"] += 1
                elif old[:2] == actual[:2]:
                    if receipt.get("sha256") == digest:
                        counts["SAME_INODE_SAME_BYTES_DRIFT"] += 1
                    else:
                        counts["SAME_INODE_CONTENT_CHANGED_BLOCKED"] += 1
                else:
                    try:
                        prior = prior_archive_verified(
                            SETTINGS["state"], folder, scope, source.name,
                            receipt, move=move, audit=audit)
                    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
                        prior = False
                    if prior:
                        counts["NEW_INODE_PRIOR_ARCHIVE_VERIFIED"] += 1
                    else:
                        counts["NEW_INODE_PRIOR_ARCHIVE_UNVERIFIED"] += 1
    finally:
        os.close(lockfd)
    for code in ("MATCH", "NEW_INODE_PRIOR_ARCHIVE_VERIFIED",
                 "NEW_INODE_PRIOR_ARCHIVE_UNVERIFIED",
                 "SAME_INODE_SAME_BYTES_DRIFT",
                 "SAME_INODE_CONTENT_CHANGED_BLOCKED",
                 "UNSTABLE_SOURCE", "NO_SENT_RECEIPT", "RECEIPT_INVALID"):
        if counts[code]:
            print("GROUP_ARCHIVE_PROOF " + code + " " + str(counts[code]))
    print("GROUP_ARCHIVE_PROOF_READ_ONLY")
    print("NO_SOURCE_CHANGED")
    print("NO_RECEIPT_CHANGED")
    print("NO_ARCHIVE_OR_PURGE")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise RuntimeError("MISSING_PARENT")
        run(Path(sys.argv[1]))
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        print("GROUP_ARCHIVE_PROOF_BLOCKED", file=sys.stderr)
        sys.exit(1)
