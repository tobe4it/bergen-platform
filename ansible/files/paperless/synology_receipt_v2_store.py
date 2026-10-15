#!/usr/bin/env python3
"""OFFLINE ONLY: immutable PREPARED/SENT event journal for proposed NAS v2 sender.

No CLI, configured production paths, sender integration or transfer operations.
The caller must independently verify remote delivery before making SENT evidence.
Do not deploy to DSM from this module alone.
"""
import json
import os
import re
import secrets
import stat
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

from synology_receipt_versions import incarnation_id, incarnation_receiver_destination, legacy_id, validate

NONCE = re.compile(r"[0-9a-f]{32}\Z")
PREPARED_KEYS = frozenset({
    "schema_version", "receipt_id", "status", "scope", "source",
    "sha256", "signature", "destination", "incarnation_nonce",
})
SENT_KEYS = PREPARED_KEYS | {"transfer_evidence"}
MAX_RECORD_BYTES = 4096


def prepared_record(scope, source, sha256, signature, incarnation_nonce):
    """Construct a prospective PREPARED event; does not allocate an incarnation."""
    obj = {
        "schema_version": 2,
        "receipt_id": incarnation_id(scope, source, sha256, signature, incarnation_nonce),
        "status": "PREPARED",
        "scope": scope, "source": source, "sha256": sha256,
        "signature": list(signature),
        "destination": incarnation_receiver_destination(scope, source, sha256, signature, incarnation_nonce),
        "incarnation_nonce": incarnation_nonce,
    }
    _validate(obj)
    return obj


def sent_record(prepared, transfer_evidence):
    """Construct SENT using externally supplied evidence, not remote verification."""
    _validate(prepared)
    if prepared["status"] != "PREPARED":
        raise ValueError("PREPARED_EVENT_REQUIRED")
    result = dict(prepared, status="SENT", transfer_evidence=transfer_evidence)
    _validate(result)
    return result


def _validate(record):
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int:
        raise ValueError("INVALID_V2_EVENT")
    status = record.get("status")
    expected_keys = PREPARED_KEYS if status == "PREPARED" else SENT_KEYS if status == "SENT" else None
    if expected_keys is None or set(record) != expected_keys or record["schema_version"] != 2:
        raise ValueError("INVALID_V2_EVENT_FIELDS")
    if not isinstance(record.get("incarnation_nonce"), str) or not NONCE.fullmatch(record["incarnation_nonce"]):
        raise ValueError("INVALID_INCARNATION_NONCE")
    try:
        receipt_id = incarnation_id(record["scope"], record["source"],
                                record["sha256"], record["signature"],
                                record["incarnation_nonce"])
        dest = incarnation_receiver_destination(record["scope"], record["source"],
                                    record["sha256"], record["signature"],
                                    record["incarnation_nonce"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("INVALID_INCARNATION_FIELDS") from exc
    if record["receipt_id"] != receipt_id or record["destination"] != dest:
        raise ValueError("EVENT_ID_OR_DESTINATION_MISMATCH")
    if status == "SENT":
        evidence = record["transfer_evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {
                "receiver_source", "receiver_sha256", "new_file_confirmed"}:
            raise ValueError("INVALID_TRANSFER_EVIDENCE")
        if (evidence["receiver_source"] != dest
                or evidence["receiver_sha256"] != record["sha256"]
                or evidence["new_file_confirmed"] is not True):
            raise ValueError("TRANSFER_EVIDENCE_MISMATCH")
    return status


def _canonical(record):
    _validate(record)
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("EVENT_TOO_LARGE")
    return raw


def _directory_fd(directory):
    if (not isinstance(directory, Path) or not directory.is_absolute()
            or directory == Path("/") or ".." in directory.parts):
        raise ValueError("PRIVATE_ABSOLUTE_DIRECTORY_REQUIRED")
    before = directory.lstat()
    if (not stat.S_ISDIR(before.st_mode) or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o700):
        raise RuntimeError("UNSAFE_JOURNAL_DIRECTORY")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    actual = os.fstat(fd)
    if (actual.st_dev != before.st_dev or actual.st_ino != before.st_ino
            or actual.st_uid != before.st_uid or actual.st_mode != before.st_mode):
        os.close(fd)
        raise RuntimeError("JOURNAL_DIRECTORY_CHANGED")
    return fd


def _read_checked(dirfd, filename):
    before = os.stat(filename, dir_fd=dirfd, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= MAX_RECORD_BYTES):
        raise RuntimeError("UNSAFE_JOURNAL_FILE")
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    try:
        current = os.fstat(fd)
        if (current.st_dev != before.st_dev or current.st_ino != before.st_ino
                or current.st_uid != before.st_uid or current.st_mode != before.st_mode
                or current.st_size != before.st_size or current.st_nlink != 1):
            raise RuntimeError("JOURNAL_FILE_CHANGED")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
        return data
    finally:
        os.close(fd)


def _publish_no_replace(dirfd, filename, raw):
    """Durable create-only; ambiguous fsync failure must be resolved on retry."""
    temp = ".v2-receipt-" + secrets.token_hex(16) + ".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=dirfd)
    try:
        try:
            with os.fdopen(fd, "wb", closefd=False) as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
        finally:
            os.close(fd)
        try:
            os.link(temp, filename, src_dir_fd=dirfd, dst_dir_fd=dirfd,
                    follow_symlinks=False)
            created = True
        except FileExistsError:
            if _read_checked(dirfd, filename) != raw:
                raise RuntimeError("CONFLICTING_JOURNAL_EVENT")
            created = False
        os.fsync(dirfd)
        return created
    finally:
        # Only the temporary file created in this call may be unlinked.
        os.unlink(temp, dir_fd=dirfd)
        os.fsync(dirfd)


def _lock_existing(dirfd):
    before = os.stat("sync.lock", dir_fd=dirfd, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_SYNC_LOCK")
    lockfd = os.open("sync.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    try:
        actual = os.fstat(lockfd)
        if (actual.st_dev != before.st_dev or actual.st_ino != before.st_ino
                or actual.st_mode != before.st_mode or actual.st_nlink != 1):
            raise RuntimeError("SYNC_LOCK_CHANGED")
        flock(lockfd, LOCK_EX | LOCK_NB)
        return lockfd
    except BaseException:
        os.close(lockfd)
        raise


def publish_event(directory, record):
    """Append one immutable event under the existing sender lock.

    Returns (path, created). Does not verify NAS source or remote receiver.
    For SENT, a canonical matching PREPARED event must already exist.
    Neither event is overwritten; old v1 receipts remain untouched.
    """
    status = _validate(record)
    raw = _canonical(record)
    dirfd = _directory_fd(directory)
    try:
        lockfd = _lock_existing(dirfd)
        try:
            name = record["receipt_id"] + "." + status.lower() + ".json"
            if status == "SENT":
                prepared_name = record["receipt_id"] + ".prepared.json"
                expected = dict(record)
                expected.pop("transfer_evidence")
                expected["status"] = "PREPARED"
                if _read_checked(dirfd, prepared_name) != _canonical(expected):
                    raise RuntimeError("MISSING_OR_MISMATCHED_PREPARED_EVENT")
            created = _publish_no_replace(dirfd, name, raw)
            return directory / name, created
        finally:
            os.close(lockfd)
    finally:
        os.close(dirfd)


def _checked_history(dirfd):
    """Fail-closed v1/v2 enumeration while holding the sender lock.

    Returns historical (scope, source) pairs without changing any records.
    """
    old_pattern = re.compile(r"[a-f0-9]{64}\.json\Z")
    v2_pattern = re.compile(r"(v2-[a-f0-9]{32}-[a-f0-9]{64})\.(prepared|sent)\.json\Z")
    names = os.listdir(dirfd)
    if len(names) > 10000:
        raise RuntimeError("STATE_ENTRY_LIMIT_EXCEEDED")
    identities = set()
    events = {}
    for name in sorted(names):
        is_old = bool(old_pattern.fullmatch(name))
        is_v2 = v2_pattern.fullmatch(name)
        if not (is_old or is_v2):
            if (name.endswith(".json") or name.startswith(".receipt-")
                    or name.startswith(".v2-receipt-")):
                raise RuntimeError("UNKNOWN_OR_ORPHANED_JOURNAL_ENTRY")
            continue
        raw = _read_checked(dirfd, name)
        try:
            def no_duplicates(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("DUPLICATE_JSON_KEY")
                    result[key] = value
                return result
            value = json.loads(raw, object_pairs_hook=no_duplicates)
            if not isinstance(value, dict):
                raise ValueError("INVALID_RECEIPT_OBJECT")
            scope, source = value["scope"], value["source"]
            if is_old:
                if legacy_id(scope, source) + ".json" != name:
                    raise ValueError("LEGACY_KEY_MISMATCH")
                legacy_required = {"scope", "source", "status", "sha256",
                                   "signature", "destination"}
                legacy_optional = {"prepared_at", "sent_at", "reconciled_at",
                                   "manually_confirmed_imported", "bridge_receipt",
                                   "document_id", "recovery_reason"}
                if (not legacy_required <= set(value)
                        or not set(value) <= legacy_required | legacy_optional
                        or value.get("status") not in ("PREPARED", "SENT")
                        or not isinstance(value.get("sha256"), str)
                        or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
                        or not isinstance(value.get("signature"), list)
                        or len(value["signature"]) != 5
                        or any(type(n) is not int or n < 0 for n in value["signature"])):
                    raise ValueError("INVALID_LEGACY_EVENT")
                stem = re.sub(r"[^\w. -]", "_", Path(source).stem,
                              flags=re.UNICODE).strip(" ._-")[:120] or "scan"
                if value["destination"] != scope + "/" + stem + "--nas-" + value["sha256"] + ".pdf":
                    raise ValueError("INVALID_LEGACY_DESTINATION")
            else:
                if _validate(value) != is_v2.group(2).upper():
                    raise ValueError("V2_STATUS_MISMATCH")
                if name != value["receipt_id"] + "." + value["status"].lower() + ".json":
                    raise ValueError("V2_FILE_NAME_MISMATCH")
                if _canonical(value) != raw:
                    raise ValueError("NONCANONICAL_V2_EVENT")
                events.setdefault(value["receipt_id"], {})[value["status"]] = value
            identities.add((scope, source))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("INVALID_HISTORICAL_RECEIPT") from exc
    for stages in events.values():
        if "SENT" in stages:
            if "PREPARED" not in stages:
                raise RuntimeError("SENT_WITHOUT_PREPARED")
            expected = dict(stages["SENT"])
            expected.pop("transfer_evidence")
            expected["status"] = "PREPARED"
            if stages["PREPARED"] != expected:
                raise RuntimeError("PREPARED_SENT_MISMATCH")
    return identities


def reserve_prepared(directory, scope, source, sha256, signature):
    """Mint + durably persist a random nonce before any possible transfer.

    Repeated names, including an uncertain PREPARED, cannot be retried.
    The nonce is part of the receipt basename AND remote file basename.
    This is OFFLINE ONLY, not authorization to send or delete files.
    """
    validate(scope, source, sha256, signature)
    dirfd = _directory_fd(directory)
    try:
        lockfd = _lock_existing(dirfd)
        try:
            previous = _checked_history(dirfd)
            if (scope, source) in previous:
                raise RuntimeError("HISTORICAL_NAME_REQUIRES_RECONCILIATION")
            record = prepared_record(scope, source, sha256, signature,
                                     secrets.token_hex(16))
            filename = record["receipt_id"] + ".prepared.json"
            if not _publish_no_replace(dirfd, filename, _canonical(record)):
                raise RuntimeError("NONCE_COLLISION_REQUIRES_RECONCILIATION")
            return directory / filename, record
        finally:
            os.close(lockfd)
    finally:
        os.close(dirfd)


__all__ = ["prepared_record", "sent_record", "publish_event", "reserve_prepared"]
