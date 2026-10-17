#!/usr/bin/env python3
"""Stream exactly one verified archived PDF read-only as paperless-sync.

Only for the previously committed Familie canary. This script arrives on
stdin through SSH and creates NO file/receipt/gate on the NAS. A fresh full
archive+Paperless lifecycle audit is required before and after this stream.
The wire format is one bounded JSON metadata line then exact PDF bytes.
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

ONLY = "Familie/Bergen-Platform-fuer-Dummies.pdf"
HEX = re.compile(r"[0-9a-f]{64}\Z")
MONTH = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])\Z")
PREPARED_KEYS = frozenset({
    "schema_version", "archive_type", "scope", "source", "sender_receipt",
    "bridge_receipt", "document_id", "sha256", "signature", "archive_site",
    "archive_scope_dir", "archive_month", "archive_name", "stage",
})


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def no_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JOURNAL_FIELD")
        result[key] = value
    return result


def read_event(dirfd, name, uid):
    before = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == uid
            and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600
            and 0 < before.st_size <= 4096, "UNSAFE_JOURNAL")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                 dir_fd=dirfd)
    try:
        now = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size,
                 before.st_uid, before.st_mode) ==
                (now.st_dev, now.st_ino, now.st_size,
                 now.st_uid, now.st_mode), "JOURNAL_CHANGED")
        raw = os.read(fd, 4097)
        require(len(raw) == before.st_size, "JOURNAL_SIZE_CHANGED")
    finally:
        os.close(fd)
    event = json.loads(raw, object_pairs_hook=no_duplicate_pairs)
    require(isinstance(event, dict) and
            raw == (json.dumps(event, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False) + "\n").encode("ascii"),
            "NONCANONICAL_JOURNAL")
    return event


def verify_pair(prepared, archived, *, scope, filename, sender_id,
                archive_dir):
    """Pure validation used in synthetic tests, no filesystem interaction."""
    require(isinstance(prepared, dict) and isinstance(archived, dict)
            and set(prepared) == PREPARED_KEYS
            and set(archived) == PREPARED_KEYS | {"archived_at"}
            and all(archived[k] == prepared[k] for k in
                    PREPARED_KEYS - {"stage"})
            and prepared["stage"] == "ARCHIVE_PREPARED"
            and archived["stage"] == "ARCHIVED", "INCOMPLETE_ARCHIVE_PAIR")
    require(prepared["schema_version"] == 1 and
            type(prepared["schema_version"]) is int and
            prepared["archive_type"] == "same_subvolume_rename" and
            prepared["scope"] == scope and
            prepared["source"] == filename and
            prepared["sender_receipt"] == sender_id + ".json" and
            prepared["archive_name"] == sender_id + ".pdf" and
            prepared["archive_site"] == "paperless-scan" and
            prepared["archive_scope_dir"] == str(archive_dir) and
            isinstance(prepared["archive_month"], str) and
            MONTH.fullmatch(prepared["archive_month"]) and
            type(prepared["document_id"]) is int and
            prepared["document_id"] == 8 and
            isinstance(prepared["bridge_receipt"], str) and
            re.fullmatch(r"[0-9a-f]{24}[.]json", prepared["bridge_receipt"]) and
            isinstance(prepared["sha256"], str) and
            HEX.fullmatch(prepared["sha256"]) and
            isinstance(prepared["signature"], list) and
            len(prepared["signature"]) == 5 and
            all(type(n) is int and n >= 0 for n in prepared["signature"]) and
            isinstance(archived["archived_at"], str) and
            0 < len(archived["archived_at"]) < 70,
            "RECOVERY_JOURNAL_PROOF_MISMATCH")
    return prepared


def verify_pdf_stat(info, signature, max_size):
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and 0 < info.st_size <= max_size
            and [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
            == signature[:4] and info.st_ctime_ns >= signature[4],
            "ARCHIVED_PDF_CHANGED")


def stream_original(parent, only):
    require(parent.is_absolute() and parent != Path("/")
            and ".." not in parent.parts and only == ONLY,
            "INVALID_RECOVERY_REQUEST")
    binpath = parent / "bin"
    bs = binpath.lstat()
    require(stat.S_ISDIR(bs.st_mode) and bs.st_uid == 0
            and stat.S_IMODE(bs.st_mode) == 0o755,
            "UNTRUSTED_NAS_BIN")
    sys.path.insert(0, str(binpath))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state
    import synology_same_volume_archive_move as move

    user = pwd.getpwnam("paperless-sync")
    require(user.pw_uid != 0 and os.geteuid() == user.pw_uid
            and SETTINGS["parent"] == parent
            and SETTINGS["sync_user"] == user.pw_name,
            "UNTRUSTED_NAS_IDENTITY")
    secure_state()
    matching = [source for source, scope in SETTINGS["sources"]
                if scope == "Familie"]
    require(len(matching) == 1, "INVALID_NAS_SCOPE_CONFIG")
    source = matching[0]
    archive = move._validated_protected_scope(source, "Familie", user.pw_uid)
    sender_id = hashlib.sha256(
        ("Familie\0Bergen-Platform-fuer-Dummies.pdf").encode("utf-8")
    ).hexdigest()
    state = SETTINGS["state"]
    lockstat = (state / "sync.lock").lstat()
    require(stat.S_ISREG(lockstat.st_mode) and
            lockstat.st_uid == user.pw_uid and
            stat.S_IMODE(lockstat.st_mode) == 0o600 and
            lockstat.st_nlink == 1, "UNSAFE_SENDER_LOCK")
    lockfd = os.open(state / "sync.lock",
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        flock(lockfd, LOCK_EX | LOCK_NB)
        journalfd = move._check_dir(state / move.JOURNAL_DIR, user.pw_uid)
        try:
            prepared = read_event(journalfd, sender_id + ".prepared.json",
                                  user.pw_uid)
            archived = read_event(journalfd, sender_id + ".archived.json",
                                  user.pw_uid)
            event = verify_pair(
                prepared, archived, scope="Familie",
                filename="Bergen-Platform-fuer-Dummies.pdf",
                sender_id=sender_id, archive_dir=archive)
        finally:
            os.close(journalfd)
        try:
            (source / "Bergen-Platform-fuer-Dummies.pdf").lstat()
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("SOURCE_PRESENT")
        sender = move._read_receipt(state / (sender_id + ".json"),
                                    "Familie",
                                    "Bergen-Platform-fuer-Dummies.pdf",
                                    event["signature"], event["sha256"])
        require(sender["destination"].startswith("Familie/"),
                "SENDER_SCOPE_MISMATCH")
        monthfd = move._check_dir(
            archive / event["archive_month"], user.pw_uid)
        try:
            require(os.fstat(monthfd).st_dev == event["signature"][0],
                    "ARCHIVE_DEVICE_CHANGED")
            fd = os.open(event["archive_name"],
                         os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=monthfd)
            try:
                before = os.fstat(fd)
                verify_pdf_stat(before, event["signature"],
                                SETTINGS["max_size"])
                # Hash before emitting any data, to avoid streaming an
                # unaudited or modified document.
                digest = hashlib.sha256()
                first = b""
                tail = b""
                while True:
                    block = os.read(fd, 1024 * 1024)
                    if not block:
                        break
                    if not first:
                        first = block[:8]
                    tail = (tail + block)[-2048:]
                    digest.update(block)
                require(digest.hexdigest() == event["sha256"]
                        and first.startswith(b"%PDF-")
                        and b"%%EOF" in tail,
                        "ARCHIVE_SHA_OR_PDF_INVALID")
                os.lseek(fd, 0, os.SEEK_SET)
                header = (json.dumps({
                    "schema_version": 1, "sha256": event["sha256"],
                    "bytes": before.st_size,
                }, sort_keys=True, separators=(",", ":")) + "\n").encode()
                out = sys.stdout.buffer
                out.write(header)
                streamed_hash = hashlib.sha256()
                streamed = 0
                while True:
                    block = os.read(fd, 1024 * 1024)
                    if not block:
                        break
                    streamed_hash.update(block)
                    streamed += len(block)
                    require(streamed <= before.st_size,
                            "ARCHIVE_SIZE_CHANGED_DURING_STREAM")
                    out.write(block)
                out.flush()
                after = os.fstat(fd)
                require(streamed == before.st_size
                        and streamed_hash.hexdigest() == event["sha256"]
                        and (before.st_dev, before.st_ino, before.st_size,
                             before.st_mtime_ns, before.st_ctime_ns) ==
                        (after.st_dev, after.st_ino, after.st_size,
                         after.st_mtime_ns, after.st_ctime_ns),
                        "ARCHIVE_CHANGED_DURING_STREAM")
            finally:
                os.close(fd)
        finally:
            os.close(monthfd)
    finally:
        os.close(lockfd)


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 3, "EXPECTED_TWO_ARGUMENTS")
        stream_original(Path(sys.argv[1]), sys.argv[2])
    except Exception:
        print("READ_ONLY_NAS_RECOVERY_BLOCKED", file=sys.stderr)
        raise SystemExit(3)
