#!/usr/bin/env python3
"""Pure read-only lifecycle reconciliation, not archive authorization.

Match every verified live NAS original to one ACL-verified Paperless import;
allow exactly one independently proven DELETED_BY_USER event for document 26.
Unknown/missing/mismatched evidence blocks the entire report.
"""
import hashlib
import json
import re
import sys

DIGEST = re.compile(r"[0-9a-f]{64}\Z")
BRIDGE = re.compile(r"[0-9a-f]{24}\.json\Z")
SENDER = re.compile(r"[0-9a-f]{64}\.json\Z")
SCOPES = ("Privat/thomas", "Privat/nadja", "Eltern", "Familie")
EVENT = "f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26"
JOURNAL_SHA = "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a"


def json_lines(text, label):
    if not isinstance(text, str):
        raise RuntimeError("INVALID_" + label + "_STREAM")
    values = [json.loads(x) for x in text.splitlines() if x.strip()]
    if len(values) > 10000 or not all(isinstance(x, dict) for x in values):
        raise RuntimeError("INVALID_" + label + "_RECORDS")
    return values


def one_with_marker(lines, label):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_" + label + "_STREAM")
    entries = [x for x in lines.splitlines() if x.strip()]
    if len(entries) != 2 or entries[1] != "NO_FILES_CHANGED":
        raise RuntimeError("INVALID_" + label + "_READ_ONLY_PROOF")
    result = json.loads(entries[0])
    if not isinstance(result, dict):
        raise RuntimeError("INVALID_" + label + "_PROOF")
    return result


def canonical(record):
    return (json.dumps(record, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def compare(nas_lines, paperless_lines, journal_lines, nas_deleted_lines):
    nas = json_lines(nas_lines, "NAS")
    imported = json_lines(paperless_lines, "PAPERLESS")
    journal = one_with_marker(journal_lines, "JOURNAL")
    deleted_nas = one_with_marker(nas_deleted_lines, "DELETED_NAS")
    if (hashlib.sha256(canonical(journal)).hexdigest() != JOURNAL_SHA
            or journal.get("event_id") != EVENT
            or journal.get("event") != "DELETED_BY_USER"
            or journal.get("document_id") != 26
            or journal.get("nas_original_absent") is not True
            or journal.get("paperless_document_absent") is not True
            or journal.get("original_filename_absent") is not True):
        raise RuntimeError("INVALID_PUBLISHED_USER_DELETION")
    if (set(deleted_nas) != {
            "schema_version", "sender_receipt", "scope", "source",
            "receiver_source", "sha256", "sender_status", "nas_original_absent"}
            or deleted_nas != {
                "schema_version": 1,
                "sender_receipt": journal["sender_receipt"],
                "scope": journal["scope"], "source": journal["source"],
                "receiver_source": journal["receiver_source"],
                "sha256": journal["sha256"],
                "sender_status": "SENT", "nas_original_absent": True,
            }):
        raise RuntimeError("DELETED_NAS_EVIDENCE_MISMATCH")
    by_receiver = {}
    deleted_proofs = []
    for item in imported:
        if (set(item) not in (
                {"schema_version", "status", "bridge_receipt",
                 "receiver_source", "sha256", "document_id"},
                {"schema_version", "status", "bridge_receipt", "sender_receipt",
                 "receiver_source", "sha256", "document_id"})
                or type(item["schema_version"]) is not int or item["schema_version"] != 1
                or type(item["document_id"]) is not int or item["document_id"] <= 0
                or not isinstance(item["receiver_source"], str)
                or not isinstance(item["bridge_receipt"], str)
                or not BRIDGE.fullmatch(item["bridge_receipt"])
                or not isinstance(item["sha256"], str)
                or not DIGEST.fullmatch(item["sha256"])
                or item["receiver_source"] in by_receiver):
            raise RuntimeError("INVALID_OR_DUPLICATE_LIVE_IMPORT")
        if item["status"] == "IMPORTED":
            if "sender_receipt" in item:
                raise RuntimeError("UNEXPECTED_SENDER_FOR_LIVE_IMPORT")
        elif item["status"] == "DELETED_BY_USER":
            if item != {
                "schema_version": 1, "status": "DELETED_BY_USER",
                "bridge_receipt": journal["bridge_receipt"],
                "sender_receipt": journal["sender_receipt"],
                "receiver_source": journal["receiver_source"],
                "sha256": journal["sha256"],
                "document_id": journal["document_id"],
            }:
                raise RuntimeError("DELETED_IMPORT_NOT_JOURNALED")
            deleted_proofs.append(item)
        else:
            raise RuntimeError("UNKNOWN_IMPORT_LIFECYCLE_STATE")
        by_receiver[item["receiver_source"]] = item
    if len(deleted_proofs) != 1:
        raise RuntimeError("REQUIRE_EXACTLY_ONE_JOURNALED_DELETION")
    seen = set()
    counts = {scope: [0, 0] for scope in SCOPES}
    for item in nas:
        if set(item) != {"sender_receipt", "scope", "source", "receiver_source", "sha256"}:
            raise RuntimeError("INVALID_NAS_RECORD")
        scope, source, receiver = item["scope"], item["source"], item["receiver_source"]
        if (scope not in counts or not isinstance(source, str)
                or not source.lower().endswith(".pdf")
                or "/" in source or "\\" in source or source in (".", "..")
                or not isinstance(receiver, str) or not receiver.startswith(scope + "/")
                or receiver in seen or receiver == journal["receiver_source"]
                or not isinstance(item["sender_receipt"], str)
                or not SENDER.fullmatch(item["sender_receipt"])
                or not isinstance(item["sha256"], str)
                or not DIGEST.fullmatch(item["sha256"])
                or hashlib.sha256((scope + "\0" + source).encode("utf-8")).hexdigest() + ".json"
                    != item["sender_receipt"]):
            raise RuntimeError("INVALID_OR_DUPLICATE_NAS_SOURCE")
        seen.add(receiver)
        proof = by_receiver.get(receiver)
        if (proof is None or proof["status"] != "IMPORTED"
                or proof["sha256"] != item["sha256"]):
            raise RuntimeError("MISSING_OR_MISMATCHED_LIVE_IMPORT " + receiver)
        counts[scope][0] += 1
        counts[scope][1] += 1
        print("LIVE_IMPORTED", scope, "document", proof["document_id"],
              "bridge", proof["bridge_receipt"], "sender", item["sender_receipt"])
    if set(by_receiver) != seen | {journal["receiver_source"]}:
        raise RuntimeError("UNMATCHED_OR_MISSING_LIFECYCLE_RECEIPT")
    if not nas:
        raise RuntimeError("NO_VERIFIED_LIVE_NAS_SOURCES")
    print("DELETED_BY_USER_CONFIRMED", journal["document_id"],
          "bridge", journal["bridge_receipt"], "sender", journal["sender_receipt"])
    print("NAS_ORIGINAL_ABSENT_AND_JOURNALED", journal["scope"] + "/" + journal["source"])
    print("PAPERLESS_LIVE_IMPORTED", len(imported) - 1)
    print("NAS_SENT_VERIFIED", len(nas))
    for scope, (sent, matched) in counts.items():
        print("SCOPE_COUNTS", scope, "SENT", sent, "LIVE_IMPORTED", matched)
    print("DELETED_BY_USER", 1)
    print("IMPORT_LIFECYCLE_RECONCILED")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("NO_RECEIPTS_CHANGED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or set(data) != {
            "nas", "paperless", "journal", "nas_deleted"}:
        raise RuntimeError("INVALID_LIFECYCLE_COMPARISON_REQUEST")
    compare(data["nas"], data["paperless"], data["journal"], data["nas_deleted"])
