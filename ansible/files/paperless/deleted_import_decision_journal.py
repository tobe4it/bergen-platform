#!/usr/bin/env python3
"""Offline-only, append-only deletion decision journal primitives.

NOT deployed or invoked by Ansible. No CLI and no production path defaults.
The caller must separately obtain fresh, independently verified live evidence.
"""
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
BRIDGE_ID = re.compile(r"[0-9a-f]{24}\.json\Z")
SENDER_ID = re.compile(r"[0-9a-f]{64}\.json\Z")
SCOPE = {"Privat/thomas", "Privat/nadja", "Eltern", "Familie"}
RECORD_KEYS = {
    "schema_version", "event", "event_id", "document_id",
    "bridge_receipt", "sender_receipt", "scope", "source",
    "receiver_source", "sha256", "confirmed_by", "confirmed_at",
    "decision_reason",
}


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _valid_basename(name):
    return (isinstance(name, str) and 0 < len(name) <= 255
            and name not in (".", "..") and "/" not in name
            and "\\" not in name and "\x00" not in name
            and name.lower().endswith(".pdf"))


def _utc_timestamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("CONFIRMATION_TIME_NOT_UTC")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_CONFIRMATION_TIME") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("INVALID_CONFIRMATION_TIME")
    if not (datetime(2020, 1, 1, tzinfo=timezone.utc)
            <= timestamp <= datetime.now(timezone.utc)):
        raise ValueError("CONFIRMATION_TIME_OUT_OF_RANGE")


def _identity(record):
    return {key: record[key] for key in (
        "document_id", "bridge_receipt", "sender_receipt", "sha256"
    )}


def validate_record(record):
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise ValueError("INVALID_DECISION_SCHEMA")
    if (type(record["schema_version"]) is not int or record["schema_version"] != 1
            or record["event"] != "DELETED_IN_PAPERLESS"
            or record["decision_reason"] != "explicit_user_deletion"
            or type(record["document_id"]) is not int or record["document_id"] <= 0
            or not isinstance(record["bridge_receipt"], str)
            or not BRIDGE_ID.fullmatch(record["bridge_receipt"])
            or not isinstance(record["sender_receipt"], str)
            or not SENDER_ID.fullmatch(record["sender_receipt"])
            or not isinstance(record["sha256"], str)
            or not HEX64.fullmatch(record["sha256"])
            or record["scope"] not in SCOPE
            or not _valid_basename(record["source"])
            or not isinstance(record["receiver_source"], str)
            or not record["receiver_source"].startswith(record["scope"] + "/")
            or not record["receiver_source"].endswith(
                "--nas-" + record["sha256"] + ".pdf")
            or not isinstance(record["confirmed_by"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", record["confirmed_by"])):
        raise ValueError("INVALID_DECISION_FIELDS")
    _utc_timestamp(record["confirmed_at"])
    expected_id = hashlib.sha256(_canonical(_identity(record))).hexdigest()
    if record["event_id"] != expected_id:
        raise ValueError("DECISION_IDENTITY_MISMATCH")
    return expected_id


def build_record(nas, deleted, confirmed_by, confirmed_at,
                 approved_document_id, approved_bridge_receipt):
    """Build from the two live-evidence payloads; caller validates their provenance.

    This does not itself establish that the inputs were obtained from live
    Paperless/NAS. The future Ansible integration must perform that step.
    """
    if not isinstance(nas, dict) or not isinstance(deleted, dict):
        raise ValueError("INVALID_PROOF")
    if (set(nas) != {"sender_receipt", "scope", "source",
                     "receiver_source", "sha256"}
            or set(deleted) != {"schema_version", "bridge_receipt",
                               "document_id", "receiver_source", "sha256",
                               "proposed_status", "live_document_absent",
                               "original_filename_absent"}
            or type(approved_document_id) is not int
            or approved_document_id <= 0
            or deleted["document_id"] != approved_document_id
            or deleted["bridge_receipt"] != approved_bridge_receipt
            or deleted["proposed_status"] != "DELETED_IN_PAPERLESS"
            or deleted["live_document_absent"] is not True
            or deleted["original_filename_absent"] is not True
            or nas["receiver_source"] != deleted["receiver_source"]
            or nas["sha256"] != deleted["sha256"]):
        raise ValueError("DELETION_PROOF_OR_APPROVAL_MISMATCH")
    record = {
        "schema_version": 1,
        "event": "DELETED_IN_PAPERLESS",
        "document_id": approved_document_id,
        "bridge_receipt": approved_bridge_receipt,
        "sender_receipt": nas["sender_receipt"],
        "scope": nas["scope"],
        "source": nas["source"],
        "receiver_source": nas["receiver_source"],
        "sha256": nas["sha256"],
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
        "decision_reason": "explicit_user_deletion",
    }
    record["event_id"] = hashlib.sha256(_canonical(_identity(record))).hexdigest()
    validate_record(record)
    return record


def _secure_directory(directory):
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise ValueError("ABSOLUTE_JOURNAL_DIRECTORY_REQUIRED")
    st = directory.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise RuntimeError("UNSAFE_JOURNAL_DIRECTORY")


def _read_existing(path, expected):
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o600
            or st.st_size != len(expected)):
        raise RuntimeError("UNSAFE_OR_CONFLICTING_DECISION")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_ino != st.st_ino:
            raise RuntimeError("DECISION_FILE_CHANGED")
        with os.fdopen(fd, "rb", closefd=False) as f:
            if f.read(len(expected) + 1) != expected:
                raise RuntimeError("CONFLICTING_DECISION")
    finally:
        os.close(fd)


def write_decision(directory, record):
    """Durably publish once via fsynced temp + no-overwrite hard link.

    Returns (path, created). A repeat with byte-identical content is a no-op;
    conflicting decisions fail closed. Does not create directories or alter
    existing journal entries. Never use without fresh live evidence.
    """
    event_id = validate_record(record)
    _secure_directory(directory)
    payload = _canonical(record)
    target = directory / (event_id + ".json")
    fd, temporary = tempfile.mkstemp(prefix=".decision-", suffix=".tmp", dir=directory)
    try:
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        try:
            os.link(temporary, target, follow_symlinks=False)
            created = True
        except FileExistsError:
            _read_existing(target, payload)
            created = False
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return target, created
    finally:
        os.unlink(temporary)
        # Make temp cleanup durable; a crash before cleanup may leave a
        # harmless .decision-*.tmp requiring explicit recovery review.
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
