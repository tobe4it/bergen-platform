#!/usr/bin/env python3
"""Pure, fail-closed preview for a manually approved deleted import.

NAS data MUST originate from the live, locked and hashed sender inventory.
Deleted data MUST originate from the live Paperless read-only DB exporter.
Never treats deletion as successful import or archival authorisation.
"""
import json
import re
import sys

SHA = re.compile(r"[a-f0-9]{64}\Z")
SENDER = re.compile(r"[a-f0-9]{64}\.json\Z")
BRIDGE = re.compile(r"[a-f0-9]{24}\.json\Z")


def records(lines):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_EVIDENCE_STREAM")
    result = []
    for line in lines.splitlines():
        if line.strip():
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise RuntimeError("INVALID_EVIDENCE_RECORD")
            result.append(obj)
            if len(result) > 10000:
                raise RuntimeError("TOO_MANY_EVIDENCE_RECORDS")
    return result


def preview(nas_lines, deleted_lines, approved_document_id, approved_bridge_receipt):
    if (type(approved_document_id) is not int or approved_document_id <= 0
            or not isinstance(approved_bridge_receipt, str)
            or not BRIDGE.fullmatch(approved_bridge_receipt)):
        raise RuntimeError("INVALID_EXPLICIT_APPROVAL")
    deleted = records(deleted_lines)
    if len(deleted) != 1:
        raise RuntimeError("REQUIRE_EXACTLY_ONE_DELETION_PROOF")
    d = deleted[0]
    if (set(d) != {"schema_version", "bridge_receipt", "document_id", "receiver_source",
                   "sha256", "proposed_status", "live_document_absent", "original_filename_absent"}
            or type(d["schema_version"]) is not int or d["schema_version"] != 1
            or type(d["document_id"]) is not int or d["document_id"] != approved_document_id
            or d["bridge_receipt"] != approved_bridge_receipt
            or d["proposed_status"] != "DELETED_IN_PAPERLESS"
            or d["live_document_absent"] is not True
            or d["original_filename_absent"] is not True
            or not isinstance(d["sha256"], str) or not SHA.fullmatch(d["sha256"])
            or not isinstance(d["receiver_source"], str)
            or not d["receiver_source"].startswith("Privat/thomas/")
            or not d["receiver_source"].endswith("--nas-" + d["sha256"] + ".pdf")):
        raise RuntimeError("INVALID_DELETION_EVIDENCE")
    nas = records(nas_lines)
    matching = []
    seen = set()
    for n in nas:
        if (set(n) != {"sender_receipt", "scope", "source", "receiver_source", "sha256"}
                or not isinstance(n["sender_receipt"], str)
                or not SENDER.fullmatch(n["sender_receipt"])
                or not isinstance(n["scope"], str)
                or not isinstance(n["source"], str)
                or not isinstance(n["receiver_source"], str)
                or not isinstance(n["sha256"], str)
                or not SHA.fullmatch(n["sha256"])
                or n["receiver_source"] in seen):
            raise RuntimeError("INVALID_OR_DUPLICATE_NAS_EVIDENCE")
        seen.add(n["receiver_source"])
        if n["receiver_source"] == d["receiver_source"]:
            matching.append(n)
    if len(matching) != 1:
        raise RuntimeError("DELETED_IMPORT_NOT_IN_VERIFIED_NAS_SOURCES")
    n = matching[0]
    if (n["scope"] != "Privat/thomas" or n["sha256"] != d["sha256"]
            or n["receiver_source"] != d["receiver_source"]
            or not n["source"].lower().endswith(".pdf")):
        raise RuntimeError("DELETED_IMPORT_NAS_MISMATCH")
    print("PREVIEW_DELETED_IN_PAPERLESS", approved_document_id, "bridge", approved_bridge_receipt,
          "sender", n["sender_receipt"])
    print("NAS_ORIGINAL_VERIFIED_AND_PRESERVED", n["scope"] + "/" + n["source"])
    print("REIMPORT_NOT_REQUESTED")
    print("EXCLUDED_FROM_ARCHIVE_MATCH_READY")
    print("NO_RECEIPT_STATUS_CHANGED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    obj = json.load(sys.stdin)
    if not isinstance(obj, dict) or set(obj) != {"nas", "deleted", "approved_document_id", "approved_bridge_receipt"}:
        raise RuntimeError("INVALID_PREVIEW_INPUT")
    preview(obj["nas"], obj["deleted"], obj["approved_document_id"], obj["approved_bridge_receipt"])
