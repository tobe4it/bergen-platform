#!/usr/bin/env python3
"""Read-only in-guest preflight for one DELETED_BY_USER v2 journal record.

Receives the freshly validated canonical record via stdin. Never creates,
updates, renames or deletes files. Must run as the restricted ingest user.
"""
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from pathlib import Path

DIRECTORY = Path("/var/lib/paperless-ingest/deletion-decisions")
PARENT = DIRECTORY.parent
EXPECTED_USER = "paperless-ingest"
EXPECTED_UID = 997
EXPECTED_GID = 988
EXPECTED_EVENT = "2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90"
EXPECTED_SHA = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
EXPECTED_PAYLOAD_HASH = "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b"


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def validate(record):
    if not isinstance(record, dict):
        raise RuntimeError("INVALID_JOURNAL_PAYLOAD")
    if (record.get("schema_version") != 2
            or record.get("event") != "DELETED_BY_USER"
            or record.get("document_id") != 15
            or record.get("event_id") != EXPECTED_EVENT
            or record.get("sha256") != EXPECTED_SHA
            or record.get("scope") != "Privat/thomas"
            or record.get("source") != "Gebuehren.pdf"
            or record.get("bridge_receipt") != "7a92b91deb7b2e8e35f9f710.json"
            or record.get("sender_receipt") != "adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json"
            or record.get("receiver_source") != "Privat/thomas/Gebuehren--nas-" + EXPECTED_SHA + ".pdf"
            or record.get("nas_original_absent") is not True
            or record.get("paperless_document_absent") is not True
            or record.get("original_filename_absent") is not True
            or record.get("sender_status") != "SENT"
            or record.get("confirmed_by") != "thomas"
            or record.get("confirmation_method") != "explicit_user_chat"
            or record.get("confirmation_date") != "2026-10-14"
            or record.get("decision_reason") != "explicit_deletion_on_paperless_and_nas"):
        raise RuntimeError("UNEXPECTED_USER_DELETION_TARGET")
    identity = {key: record[key] for key in (
        "event", "document_id", "bridge_receipt", "sender_receipt",
        "scope", "source", "receiver_source", "sha256")}
    event_id = hashlib.sha256(canonical(
        ["bergen-paperless-user-deletion-v2", identity])).hexdigest()
    if event_id != EXPECTED_EVENT or not re.fullmatch(r"[0-9a-f]{64}", event_id):
        raise RuntimeError("EVENT_ID_MISMATCH")
    payload = canonical(record)
    if hashlib.sha256(payload).hexdigest() != EXPECTED_PAYLOAD_HASH:
        raise RuntimeError("UNEXPECTED_JOURNAL_PAYLOAD_SHA256")
    return payload


def check_directory(directory):
    account = pwd.getpwnam(EXPECTED_USER)
    if (os.geteuid() != EXPECTED_UID
            or account.pw_uid != EXPECTED_UID
            or account.pw_gid != EXPECTED_GID
            or os.getegid() != EXPECTED_GID):
        raise RuntimeError("RESTRICTED_INGEST_USER_REQUIRED")
    parent = os.lstat(directory.parent)
    root = os.lstat("/")
    if (not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != 0 or parent.st_gid != EXPECTED_GID
            or stat.S_IMODE(parent.st_mode) != 0o750
            or parent.st_dev != root.st_dev):
        raise RuntimeError("UNSAFE_JOURNAL_PARENT")
    original = os.lstat(directory)
    if (not stat.S_ISDIR(original.st_mode)
            or original.st_uid != EXPECTED_UID
            or original.st_gid != EXPECTED_GID
            or stat.S_IMODE(original.st_mode) != 0o700
            or original.st_dev != root.st_dev):
        raise RuntimeError("UNSAFE_JOURNAL_DIRECTORY")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    actual = os.fstat(fd)
    if (actual.st_ino != original.st_ino or actual.st_dev != original.st_dev
            or actual.st_uid != EXPECTED_UID
            or actual.st_gid != EXPECTED_GID
            or stat.S_IMODE(actual.st_mode) != 0o700):
        os.close(fd)
        raise RuntimeError("JOURNAL_DIRECTORY_CHANGED")
    return fd


def plan(record, directory=DIRECTORY):
    payload = validate(record)
    fd = check_directory(directory)
    try:
        name = EXPECTED_EVENT + ".json"
        try:
            existing = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            print("READY_TO_PUBLISH", name)
        else:
            if (not stat.S_ISREG(existing.st_mode)
                    or existing.st_uid != EXPECTED_UID
                    or existing.st_gid != EXPECTED_GID
                    or existing.st_nlink != 1
                    or stat.S_IMODE(existing.st_mode) != 0o600
                    or existing.st_size != len(payload)):
                raise RuntimeError("UNSAFE_OR_CONFLICTING_EXISTING_JOURNAL")
            item_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                current = os.fstat(item_fd)
                if (current.st_ino != existing.st_ino
                        or current.st_dev != existing.st_dev
                        or current.st_nlink != 1
                        or current.st_uid != EXPECTED_UID
                        or current.st_gid != EXPECTED_GID
                        or stat.S_IMODE(current.st_mode) != 0o600
                        or os.read(item_fd, len(payload) + 1) != payload):
                    raise RuntimeError("CONFLICTING_JOURNAL_PAYLOAD")
            finally:
                os.close(item_fd)
            print("ALREADY_IDENTICAL", name)
    finally:
        os.close(fd)
    print("JOURNAL_DIRECTORY_PRIVATE_VERIFIED")
    print("JOURNAL_SHA256", hashlib.sha256(payload).hexdigest())
    print("NO_JOURNAL_WRITTEN")
    print("NO_RECEIPTS_CHANGED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    record = json.load(sys.stdin)
    plan(record)
