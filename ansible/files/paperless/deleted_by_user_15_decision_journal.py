#!/usr/bin/env python3
"""Offline-only DELETED_BY_USER v2 journal schema for document 15 and read-only preview.

No write primitive, no production directory, no sender/receiver integration.
The record describes explicitly approved absence on Paperless and NAS, not
permission to archive, restore, reimport or delete any other version.
"""
import hashlib
import json
import re
import sys
from datetime import date

SCOPE = "Privat/thomas"
SOURCE = "Gebuehren.pdf"
DOCUMENT_ID = 15
BRIDGE = "7a92b91deb7b2e8e35f9f710.json"
SENDER = "adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json"
KEYS = {
    "schema_version", "event", "event_id", "document_id",
    "bridge_receipt", "sender_receipt", "scope", "source",
    "receiver_source", "sha256", "sender_status",
    "nas_original_absent", "paperless_document_absent",
    "original_filename_absent", "confirmed_by",
    "confirmation_method", "confirmation_date", "decision_reason",
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
EXPECTED_EVENT = "2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90"
EXPECTED_PAYLOAD_HASH = "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b"


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def identity(record):
    return {key: record[key] for key in (
        "event", "document_id", "bridge_receipt", "sender_receipt",
        "scope", "source", "receiver_source", "sha256",
    )}


def validate(record):
    if not isinstance(record, dict) or set(record) != KEYS:
        raise ValueError("INVALID_USER_DELETION_JOURNAL_SCHEMA")
    if (type(record["schema_version"]) is not int or record["schema_version"] != 2
            or record["event"] != "DELETED_BY_USER"
            or type(record["document_id"]) is not int
            or record["document_id"] != DOCUMENT_ID
            or record["bridge_receipt"] != BRIDGE
            or record["sender_receipt"] != SENDER
            or record["scope"] != SCOPE
            or record["source"] != SOURCE
            or not isinstance(record["sha256"], str)
            or not SHA.fullmatch(record["sha256"])
            or record["sha256"] != EXPECTED_DIGEST
            or record["receiver_source"] != SCOPE + "/Gebuehren--nas-" + record["sha256"] + ".pdf"
            or record["sender_status"] != "SENT"
            or record["nas_original_absent"] is not True
            or record["paperless_document_absent"] is not True
            or record["original_filename_absent"] is not True
            or record["confirmed_by"] != "thomas"
            or record["confirmation_method"] != "explicit_user_chat"
            or record["confirmation_date"] != "2026-10-14"
            or record["decision_reason"] != "explicit_deletion_on_paperless_and_nas"):
        raise ValueError("INVALID_USER_DELETION_JOURNAL_FIELDS")
    try:
        date.fromisoformat(record["confirmation_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_CONFIRMATION_DATE") from exc
    expected = hashlib.sha256(canonical(["bergen-paperless-user-deletion-v2", identity(record)])).hexdigest()
    if record["event_id"] != expected or expected != EXPECTED_EVENT:
        raise ValueError("USER_DELETION_EVENT_ID_MISMATCH")
    return expected


def build(nas, deleted):
    if not isinstance(nas, dict) or not isinstance(deleted, dict):
        raise ValueError("INVALID_LIVE_EVIDENCE")
    if (set(nas) != {"schema_version", "sender_receipt", "scope", "source",
                     "receiver_source", "sha256", "sender_status", "nas_original_absent"}
            or type(nas["schema_version"]) is not int or nas["schema_version"] != 1
            or set(deleted) != {"schema_version", "bridge_receipt", "document_id",
                                "receiver_source", "sha256", "proposed_status",
                                "live_document_absent", "original_filename_absent"}
            or type(deleted["schema_version"]) is not int or deleted["schema_version"] != 1
            or nas["sender_receipt"] != SENDER
            or nas["scope"] != SCOPE or nas["source"] != SOURCE
            or nas["sender_status"] != "SENT" or nas["nas_original_absent"] is not True
            or type(deleted["document_id"]) is not int or deleted["document_id"] != DOCUMENT_ID
            or deleted["bridge_receipt"] != BRIDGE
            or deleted["proposed_status"] != "DELETED_IN_PAPERLESS"
            or deleted["live_document_absent"] is not True
            or deleted["original_filename_absent"] is not True
            or nas["sha256"] != deleted["sha256"]
            or nas["receiver_source"] != deleted["receiver_source"]):
        raise ValueError("USER_DELETION_LIVE_EVIDENCE_MISMATCH")
    record = {
        "schema_version": 2, "event": "DELETED_BY_USER",
        "document_id": DOCUMENT_ID, "bridge_receipt": BRIDGE,
        "sender_receipt": SENDER, "scope": SCOPE, "source": SOURCE,
        "receiver_source": nas["receiver_source"], "sha256": nas["sha256"],
        "sender_status": "SENT", "nas_original_absent": True,
        "paperless_document_absent": True, "original_filename_absent": True,
        "confirmed_by": "thomas", "confirmation_method": "explicit_user_chat",
        "confirmation_date": "2026-10-14",
        "decision_reason": "explicit_deletion_on_paperless_and_nas",
    }
    record["event_id"] = hashlib.sha256(canonical(
        ["bergen-paperless-user-deletion-v2", identity(record)]
    )).hexdigest()
    validate(record)
    if hashlib.sha256(canonical(record)).hexdigest() != EXPECTED_PAYLOAD_HASH:
        raise ValueError("UNEXPECTED_DOCUMENT_15_JOURNAL_PAYLOAD_HASH")
    return record


def one(lines, marker=False):
    if not isinstance(lines, str):
        raise ValueError("INVALID_EVIDENCE_STREAM")
    entries = [s for s in lines.splitlines() if s.strip()]
    if marker:
        if len(entries) != 2 or entries[1] != "NO_FILES_CHANGED":
            raise ValueError("MISSING_READ_ONLY_NAS_MARKER")
    elif len(entries) != 1:
        raise ValueError("INVALID_PAPERLESS_EVIDENCE_COUNT")
    item = json.loads(entries[0])
    if not isinstance(item, dict):
        raise ValueError("INVALID_EVIDENCE_OBJECT")
    return item


def preview(nas_lines, deleted_lines):
    nas = one(nas_lines, marker=True)
    deleted = one(deleted_lines)
    record = build(nas, deleted)
    # Full canonical record is displayed, never written to disk.
    payload = canonical(record)
    if hashlib.sha256(payload).hexdigest() != EXPECTED_PAYLOAD_HASH:
        raise ValueError("UNEXPECTED_DOCUMENT_15_JOURNAL_PAYLOAD_HASH")
    print("PROPOSED_USER_DELETION_JOURNAL_FILENAME", record["event_id"] + ".json")
    print("PROPOSED_USER_DELETION_JOURNAL_SHA256", hashlib.sha256(payload).hexdigest())
    print("PROPOSED_USER_DELETION_JOURNAL_JSON", payload.decode("ascii").strip())
    print("REUSED_FILENAME_NEW_INCARNATION_NOT_AUTHORIZED")
    print("NO_JOURNAL_WRITTEN")
    print("EXCLUDED_FROM_ARCHIVE_MATCH_READY")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    request = json.load(sys.stdin)
    if not isinstance(request, dict) or set(request) != {"nas", "deleted"}:
        raise SystemExit("INVALID_JOURNAL_PREVIEW_REQUEST")
    preview(request["nas"], request["deleted"])
