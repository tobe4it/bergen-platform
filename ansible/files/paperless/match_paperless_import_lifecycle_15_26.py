#!/usr/bin/env python3
"""Pure read-only dual-journal lifecycle reconciliation, never archive readiness."""
import hashlib
import json
import re
import sys

DIGEST = re.compile(r"[0-9a-f]{64}\Z")
BRIDGE = re.compile(r"[0-9a-f]{24}\.json\Z")
SENDER = re.compile(r"[0-9a-f]{64}\.json\Z")
SCOPES = ("Privat/thomas", "Privat/nadja", "Eltern", "Familie")
DELETIONS = {
    15: ("2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90",
         "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b",
         "7a92b91deb7b2e8e35f9f710.json",
         "adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json",
         "Gebuehren.pdf"),
    26: ("f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26",
         "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a",
         "1ebb2c1d26d7b1494d28d9cd.json",
         "7a9e41ee25d2a98c4e529472f3db2ab6c70b453a3214c1da537175bbcef1b4e8.json",
         "Gebuehren 2.pdf"),
}
SHA = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def json_lines(stream, label):
    if not isinstance(stream, str):
        raise RuntimeError("INVALID_" + label + "_STREAM")
    values = [json.loads(line) for line in stream.splitlines() if line.strip()]
    if len(values) > 10000 or not all(isinstance(x, dict) for x in values):
        raise RuntimeError("INVALID_" + label + "_RECORDS")
    return values


def journal_lines(stream):
    if not isinstance(stream, str):
        raise RuntimeError("INVALID_JOURNAL_STREAM")
    lines = [line for line in stream.splitlines() if line.strip()]
    if len(lines) != 3 or lines[-1] != "NO_FILES_CHANGED":
        raise RuntimeError("REQUIRE_TWO_PRIVATE_JOURNALS")
    values = [json.loads(line) for line in lines[:-1]]
    if not all(isinstance(x, dict) for x in values):
        raise RuntimeError("INVALID_PRIVATE_JOURNAL_RECORD")
    by_id = {}
    for item in values:
        docid = item.get("document_id")
        if type(docid) is not int or docid in by_id:
            raise RuntimeError("DUPLICATE_PRIVATE_JOURNAL")
        by_id[docid] = item
    if set(by_id) != set(DELETIONS):
        raise RuntimeError("MISSING_OR_UNKNOWN_PRIVATE_JOURNAL")
    return by_id


def one_with_marker(stream, label):
    if not isinstance(stream, str):
        raise RuntimeError("INVALID_" + label + "_STREAM")
    lines = [line for line in stream.splitlines() if line.strip()]
    if len(lines) != 2 or lines[-1] != "NO_FILES_CHANGED":
        raise RuntimeError("INVALID_" + label + "_READ_ONLY_PROOF")
    result = json.loads(lines[0])
    if not isinstance(result, dict):
        raise RuntimeError("INVALID_" + label + "_PROOF")
    return result


def verify_journals(data):
    records = journal_lines(data["journal"])
    receivers = set()
    bridges = set()
    senders = set()
    for docid, (event, digest, bridge, sender, filename) in DELETIONS.items():
        journal = records[docid]
        receiver = "Privat/thomas/" + filename[:-4] + "--nas-" + SHA + ".pdf"
        expected = {
            "schema_version": 2, "event": "DELETED_BY_USER",
            "event_id": event, "document_id": docid,
            "bridge_receipt": bridge, "sender_receipt": sender,
            "scope": "Privat/thomas", "source": filename,
            "receiver_source": receiver, "sha256": SHA,
            "sender_status": "SENT", "nas_original_absent": True,
            "paperless_document_absent": True, "original_filename_absent": True,
            "confirmed_by": "thomas", "confirmation_method": "explicit_user_chat",
            "confirmation_date": "2026-10-14",
            "decision_reason": "explicit_deletion_on_paperless_and_nas",
        }
        nas = one_with_marker(data["nas_deleted_" + str(docid)], "NAS_DELETED_" + str(docid))
        expected_nas = {
            "schema_version": 1, "sender_receipt": sender,
            "scope": "Privat/thomas", "source": filename,
            "receiver_source": receiver, "sha256": SHA,
            "sender_status": "SENT", "nas_original_absent": True,
        }
        if (journal != expected
                or hashlib.sha256(canonical(journal)).hexdigest() != digest
                or nas != expected_nas):
            raise RuntimeError("UNVERIFIED_JOURNAL_OR_NAS_DELETION " + str(docid))
        if receiver in receivers or bridge in bridges or sender in senders:
            raise RuntimeError("DUPLICATE_DELETION_IDENTITY")
        receivers.add(receiver)
        bridges.add(bridge)
        senders.add(sender)
    return records


def compare(nas_lines, paperless_lines, journal_stream, nas_deleted_15, nas_deleted_26):
    data = {"journal": journal_stream, "nas_deleted_15": nas_deleted_15,
            "nas_deleted_26": nas_deleted_26}
    journals = verify_journals(data)
    nas = json_lines(nas_lines, "NAS")
    imported = json_lines(paperless_lines, "PAPERLESS")
    by_receiver = {}
    bridge_names = set()
    deleted_seen = set()
    for item in imported:
        if (set(item) not in (
                {"schema_version", "status", "bridge_receipt", "receiver_source",
                 "sha256", "document_id"},
                {"schema_version", "status", "bridge_receipt", "sender_receipt",
                 "receiver_source", "sha256", "document_id"})
                or type(item["schema_version"]) is not int or item["schema_version"] != 1
                or type(item["document_id"]) is not int or item["document_id"] <= 0
                or not isinstance(item["receiver_source"], str)
                or not isinstance(item["bridge_receipt"], str)
                or not BRIDGE.fullmatch(item["bridge_receipt"])
                or not isinstance(item["sha256"], str)
                or not DIGEST.fullmatch(item["sha256"])
                or item["receiver_source"] in by_receiver
                or item["bridge_receipt"] in bridge_names):
            raise RuntimeError("INVALID_OR_DUPLICATE_LIVE_IMPORT")
        bridge_names.add(item["bridge_receipt"])
        if item["status"] == "IMPORTED":
            if "sender_receipt" in item:
                raise RuntimeError("UNEXPECTED_SENDER_FOR_LIVE_IMPORT")
        elif item["status"] == "DELETED_BY_USER":
            docid = item["document_id"]
            journal = journals.get(docid)
            if journal is None or item != {
                    "schema_version": 1, "status": "DELETED_BY_USER",
                    "bridge_receipt": journal["bridge_receipt"],
                    "sender_receipt": journal["sender_receipt"],
                    "receiver_source": journal["receiver_source"],
                    "sha256": journal["sha256"], "document_id": docid}:
                raise RuntimeError("DELETED_IMPORT_NOT_JOURNALED")
            if docid in deleted_seen:
                raise RuntimeError("DUPLICATE_JOURNALED_DELETION")
            deleted_seen.add(docid)
        else:
            raise RuntimeError("UNKNOWN_IMPORT_LIFECYCLE_STATE")
        by_receiver[item["receiver_source"]] = item
    if deleted_seen != set(DELETIONS):
        raise RuntimeError("REQUIRE_EXACTLY_TWO_JOURNALED_DELETIONS")
    seen = set()
    counts = {scope: [0, 0] for scope in SCOPES}
    deleted_receivers = {journal["receiver_source"] for journal in journals.values()}
    for item in nas:
        if set(item) != {"sender_receipt", "scope", "source", "receiver_source", "sha256"}:
            raise RuntimeError("INVALID_NAS_RECORD")
        scope, source, receiver = item["scope"], item["source"], item["receiver_source"]
        if (scope not in counts or not isinstance(source, str)
                or not source.lower().endswith(".pdf")
                or "/" in source or "\\" in source or source in (".", "..")
                or not isinstance(receiver, str) or not receiver.startswith(scope + "/")
                or receiver in seen or receiver in deleted_receivers
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
    if set(by_receiver) != seen | deleted_receivers:
        raise RuntimeError("UNMATCHED_OR_MISSING_LIFECYCLE_RECEIPT")
    if not nas:
        raise RuntimeError("NO_VERIFIED_LIVE_NAS_SOURCES")
    for docid, journal in sorted(journals.items()):
        print("DELETED_BY_USER_CONFIRMED", docid,
              "bridge", journal["bridge_receipt"], "sender", journal["sender_receipt"])
        print("NAS_ORIGINAL_ABSENT_AND_JOURNALED", journal["scope"] + "/" + journal["source"])
    print("PAPERLESS_LIVE_IMPORTED", len(imported) - len(DELETIONS))
    print("NAS_SENT_VERIFIED", len(nas))
    for scope, (sent, matched) in counts.items():
        print("SCOPE_COUNTS", scope, "SENT", sent, "LIVE_IMPORTED", matched)
    print("DELETED_BY_USER", len(DELETIONS))
    print("IMPORT_LIFECYCLE_RECONCILED")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("NO_RECEIPTS_CHANGED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or set(data) != {
            "nas", "paperless", "journal", "nas_deleted_15", "nas_deleted_26"}:
        raise RuntimeError("INVALID_DUAL_LIFECYCLE_COMPARISON_REQUEST")
    compare(data["nas"], data["paperless"], data["journal"],
            data["nas_deleted_15"], data["nas_deleted_26"])
