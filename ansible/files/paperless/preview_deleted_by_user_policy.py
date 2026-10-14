#!/usr/bin/env python3
"""Pure read-only preview for an explicitly approved two-sided user deletion.

The absence of files alone does not establish user intent. Intent is supplied
by the operator's separately recorded approval for this exact target.
Never grants archival permission or writes any journal.
"""
import hashlib
import json
import re
import sys

APPROVED_ID = 26
APPROVED_BRIDGE = "1ebb2c1d26d7b1494d28d9cd.json"
APPROVED_SENDER = "7a9e41ee25d2a98c4e529472f3db2ab6c70b453a3214c1da537175bbcef1b4e8.json"
APPROVED_SCOPE = "Privat/thomas"
APPROVED_SOURCE = "Gebuehren 2.pdf"


def one_json(lines, allow_marker=False):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_EVIDENCE_STREAM")
    values = [line for line in lines.splitlines() if line.strip()]
    if allow_marker:
        if len(values) != 2 or values[1] != "NO_FILES_CHANGED":
            raise RuntimeError("NAS_READ_ONLY_MARKER_MISSING")
    elif len(values) != 1:
        raise RuntimeError("REQUIRE_ONE_PAPERLESS_RECORD")
    obj = json.loads(values[0])
    if not isinstance(obj, dict):
        raise RuntimeError("INVALID_EVIDENCE_RECORD")
    return obj


def preview(nas_lines, paperless_lines, approved_id, approved_bridge, approved_sender):
    if (type(approved_id) is not int or approved_id != APPROVED_ID
            or approved_bridge != APPROVED_BRIDGE
            or approved_sender != APPROVED_SENDER):
        raise RuntimeError("EXPLICIT_APPROVAL_MISMATCH")
    nas = one_json(nas_lines, allow_marker=True)
    deleted = one_json(paperless_lines)
    if (set(nas) != {"schema_version", "sender_receipt", "scope", "source",
                     "receiver_source", "sha256", "sender_status", "nas_original_absent"}
            or type(nas["schema_version"]) is not int or nas["schema_version"] != 1
            or nas["sender_receipt"] != approved_sender
            or nas["scope"] != APPROVED_SCOPE
            or nas["source"] != APPROVED_SOURCE
            or nas["sender_status"] != "SENT"
            or nas["nas_original_absent"] is not True
            or not isinstance(nas["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", nas["sha256"])
            or not isinstance(nas["receiver_source"], str)):
        raise RuntimeError("INVALID_ABSENT_NAS_EVIDENCE")
    expected_receipt = hashlib.sha256(
        (APPROVED_SCOPE + "\0" + APPROVED_SOURCE).encode("utf-8")
    ).hexdigest() + ".json"
    if expected_receipt != approved_sender:
        raise RuntimeError("SENDER_RECEIPT_KEY_MISMATCH")
    expected_receiver = (APPROVED_SCOPE + "/Gebuehren 2--nas-"
                         + nas["sha256"] + ".pdf")
    if nas["receiver_source"] != expected_receiver:
        raise RuntimeError("NAS_RECEIVER_IDENTITY_MISMATCH")
    if (set(deleted) != {"schema_version", "bridge_receipt", "document_id",
                         "receiver_source", "sha256", "proposed_status",
                         "live_document_absent", "original_filename_absent"}
            or type(deleted["schema_version"]) is not int or deleted["schema_version"] != 1
            or type(deleted["document_id"]) is not int or deleted["document_id"] != approved_id
            or deleted["bridge_receipt"] != approved_bridge
            or deleted["proposed_status"] != "DELETED_IN_PAPERLESS"
            or deleted["live_document_absent"] is not True
            or deleted["original_filename_absent"] is not True
            or deleted["receiver_source"] != expected_receiver
            or deleted["sha256"] != nas["sha256"]):
        raise RuntimeError("PAPERLESS_NAS_PROOF_MISMATCH")
    print("PREVIEW_DELETED_BY_USER", approved_id, "bridge", approved_bridge,
          "sender", approved_sender)
    print("HISTORICAL_SENT_RECEIPT_VERIFIED", nas["scope"] + "/" + nas["source"])
    print("NAS_ORIGINAL_CONFIRMED_ABSENT")
    print("PAPERLESS_DOCUMENT_CONFIRMED_ABSENT")
    print("EXPLICIT_USER_APPROVAL_REQUIRED_FOR_FINAL_JOURNAL")
    print("NO_REIMPORT_OR_RESTORE")
    print("EXCLUDED_FROM_ARCHIVE_MATCH_READY")
    print("NO_RECEIPT_STATUS_CHANGED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    obj = json.load(sys.stdin)
    if not isinstance(obj, dict) or set(obj) != {
        "nas", "deleted", "approved_document_id",
        "approved_bridge_receipt", "approved_sender_receipt"
    }:
        raise RuntimeError("INVALID_PREVIEW_INPUT")
    preview(obj["nas"], obj["deleted"], obj["approved_document_id"],
            obj["approved_bridge_receipt"], obj["approved_sender_receipt"])
