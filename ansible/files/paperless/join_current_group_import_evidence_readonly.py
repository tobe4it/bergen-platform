#!/usr/bin/env python3
"""Exact read-only NAS SENT <> live Paperless group import join.

The combined input carries confidential source identities under Ansible no_log.
Output is count-only. Metadata drift may be reported but cannot authorize
archive, receipt modification, source rename or deletion.
"""
import json
import re
import sys

SHA = re.compile(r"[a-f0-9]{64}\Z")
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000
GROUPS = ("Familie", "Eltern")


def strict(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("DUPLICATE_PROOF_KEY")
        result[key] = value
    return result


def parse(raw, terminal, required):
    if not isinstance(raw, str) or len(raw) > MAX_BYTES:
        raise RuntimeError("INVALID_PROOF_STREAM")
    lines = [x for x in raw.splitlines() if x.strip()]
    if (len(lines) < 3 or lines[-3:] !=
            [terminal, "NO_FILES_CHANGED", "ARCHIVE_NOT_AUTHORIZED"]):
        raise RuntimeError("MISSING_VERIFIED_PROOF_TERMINAL")
    values = []
    for line in lines[:-3]:
        obj = json.loads(line, object_pairs_hook=strict)
        if not isinstance(obj, dict) or set(obj) != required:
            raise RuntimeError("INVALID_PROOF_FIELDS")
        receiver, sha = obj["receiver_source"], obj["sha256"]
        if (not isinstance(receiver, str)
                or not receiver.startswith(tuple(s + "/" for s in GROUPS))
                or not isinstance(sha, str) or not SHA.fullmatch(sha)
                or not receiver.endswith("--nas-" + sha + ".pdf")):
            raise RuntimeError("INVALID_RECEIVER_IDENTITY")
        values.append(obj)
        if len(values) > MAX_ROWS:
            raise RuntimeError("TOO_MANY_GROUP_DOCUMENTS")
    return values


def join(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"nas", "paperless"}:
        raise RuntimeError("INVALID_GROUP_JOIN")
    nas = parse(bundle["nas"], "NAS_CURRENT_GROUP_EVIDENCE_COMPLETE",
                {"receiver_source", "sha256", "classification"})
    live = parse(bundle["paperless"], "LIVE_GROUP_IMPORT_EVIDENCE_COMPLETE",
                 {"receiver_source", "sha256", "bridge_receipt", "document_id"})
    imported_by_name = {}
    document_ids, bridges = set(), set()
    for item in live:
        src, docid, bridge = (item["receiver_source"],
                               item["document_id"], item["bridge_receipt"])
        if (src in imported_by_name or
                type(docid) is not int or docid <= 0 or docid in document_ids
                or not isinstance(bridge, str)
                or not re.fullmatch(r"[a-f0-9]{24}\.json", bridge)
                or bridge in bridges):
            raise RuntimeError("DUPLICATE_PAPERLESS_GROUP_IDENTITY")
        imported_by_name[src] = item
        document_ids.add(docid)
        bridges.add(bridge)
    current_names = set()
    counts = {"total": 0, "live": 0, "waiting": 0, "metadata_drift": 0,
              "metadata_drift_live": 0}
    for item in nas:
        src, sha, classification = (item["receiver_source"], item["sha256"],
                                      item["classification"])
        if src in current_names or classification not in (
                "MATCH", "SAME_INODE_METADATA_DRIFT"):
            raise RuntimeError("DUPLICATE_OR_UNCLASSIFIED_NAS_SOURCE")
        current_names.add(src)
        counts["total"] += 1
        if classification == "SAME_INODE_METADATA_DRIFT":
            counts["metadata_drift"] += 1
        live_receipt = imported_by_name.get(src)
        if live_receipt is None:
            counts["waiting"] += 1
        else:
            if live_receipt["sha256"] != sha:
                raise RuntimeError("GROUP_IMPORT_SHA_MISMATCH")
            counts["live"] += 1
            if classification == "SAME_INODE_METADATA_DRIFT":
                counts["metadata_drift_live"] += 1
    return counts


def main():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise RuntimeError("GROUP_BUNDLE_TOO_LARGE")
    info = join(json.loads(raw, object_pairs_hook=strict))
    print("GROUP_CURRENT_NAS_SENT", info["total"])
    print("GROUP_CURRENT_LIVE_IMPORTED", info["live"])
    print("GROUP_CURRENT_WAITING_FOR_IMPORT", info["waiting"])
    print("GROUP_SAME_INODE_METADATA_DRIFT", info["metadata_drift"])
    print("GROUP_METADATA_DRIFT_LIVE_IMPORTED", info["metadata_drift_live"])
    print("GROUP_IMPORT_PROOF_JOIN_COMPLETE")
    print("NO_FILES_CHANGED")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("PURGE_NOT_AUTHORIZED")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        print("GROUP_IMPORT_PROOF_JOIN_BLOCKED", file=sys.stderr)
        sys.exit(1)
