#!/usr/bin/env python3
"""Pure read-only comparison of document 15 live Paperless and NAS absence.

No journal write, no receipt change, no archive authorization. A matching
absence is not itself permission to publish an immutable decision.
"""
import hashlib
import json
import re
import sys

BRIDGE = "7a92b91deb7b2e8e35f9f710.json"
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SENDER = re.compile(r"[0-9a-f]{64}\.json\Z")
SCOPE = "Privat/thomas"


def one(lines, marker=False):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_EVIDENCE_STREAM")
    values = [line for line in lines.splitlines() if line.strip()]
    if marker:
        if len(values) != 2 or values[1] != "NO_FILES_CHANGED":
            raise RuntimeError("NAS_READ_ONLY_MARKER_MISSING")
    elif len(values) != 1:
        raise RuntimeError("INVALID_EVIDENCE_COUNT")
    item = json.loads(values[0])
    if not isinstance(item, dict):
        raise RuntimeError("INVALID_EVIDENCE_OBJECT")
    return item


def compare(paperless_lines, nas_lines):
    paperless = one(paperless_lines)
    nas = one(nas_lines, marker=True)
    if (set(paperless) != {
            "schema_version", "bridge_receipt", "document_id",
            "receiver_source", "sha256", "proposed_status",
            "live_document_absent", "original_filename_absent"}
            or type(paperless["schema_version"]) is not int
            or paperless["schema_version"] != 1
            or type(paperless["document_id"]) is not int
            or paperless["document_id"] != 15
            or paperless["bridge_receipt"] != BRIDGE
            or paperless["proposed_status"] != "DELETED_IN_PAPERLESS"
            or paperless["live_document_absent"] is not True
            or paperless["original_filename_absent"] is not True
            or not isinstance(paperless["sha256"], str)
            or not DIGEST.fullmatch(paperless["sha256"])):
        raise RuntimeError("INVALID_PAPERLESS_ABSENCE_PROOF")
    if (set(nas) != {
            "schema_version", "sender_receipt", "scope", "source",
            "receiver_source", "sha256", "sender_status",
            "nas_original_absent"}
            or type(nas["schema_version"]) is not int
            or nas["schema_version"] != 1
            or nas["scope"] != SCOPE
            or nas["sender_status"] != "SENT"
            or nas["nas_original_absent"] is not True
            or not isinstance(nas["sender_receipt"], str)
            or not SENDER.fullmatch(nas["sender_receipt"])
            or not isinstance(nas["source"], str)
            or not nas["source"].lower().endswith(".pdf")
            or "/" in nas["source"] or "\\" in nas["source"]
            or nas["source"] in (".", "..")
            or hashlib.sha256((SCOPE + "\0" + nas["source"]).encode("utf-8")).hexdigest() + ".json"
                != nas["sender_receipt"]
            or nas["receiver_source"] != paperless["receiver_source"]
            or nas["sha256"] != paperless["sha256"]):
        raise RuntimeError("NAS_PAPERLESS_DELETION_PROOF_MISMATCH")
    print("PREVIEW_DELETED_BY_USER", 15, "bridge", BRIDGE)
    print("NAS_HISTORICAL_SENT_RECEIPT", nas["sender_receipt"])
    print("NAS_ORIGINAL_FILENAME", nas["source"])
    print("NAS_ORIGINAL_CONFIRMED_ABSENT")
    print("PAPERLESS_DOCUMENT_CONFIRMED_ABSENT")
    print("MATCHING_CONTENT_SHA256", nas["sha256"])
    print("USER_INTENT_CONFIRMED_IN_CHAT_NOT_A_JOURNAL_WRITE_APPROVAL")
    print("NO_JOURNAL_WRITTEN")
    print("NO_RECEIPTS_CHANGED")
    print("NO_REIMPORT_OR_RESTORE")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or set(data) != {"paperless", "nas"}:
        raise RuntimeError("INVALID_COMPARISON_REQUEST")
    compare(data["paperless"], data["nas"])
