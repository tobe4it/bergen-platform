#!/usr/bin/env python3
"""Read-only NAS SENT -> live Paperless IMPORTED reconciliation report.

Consumes one JSON object from stdin with NAS and Paperless JSONL strings.
No filesystem writes, no archive authorisation or deletion.
"""
import json
import re
import sys

DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SENDER_ID = re.compile(r"[0-9a-f]{64}\.json\Z")
BRIDGE_ID = re.compile(r"[0-9a-f]{24}\.json\Z")
SCOPES = ("Privat/thomas", "Privat/nadja", "Eltern", "Familie")


def parse(lines, keys, label):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_" + label + "_INPUT")
    result = []
    for n, line in enumerate(lines.splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict) or set(obj) != set(keys):
            raise RuntimeError("INVALID_" + label + "_RECORD " + str(n))
        result.append(obj)
        if len(result) > 10000:
            raise RuntimeError("EVIDENCE_LIMIT_EXCEEDED")
    return result


def compare(nas_lines, paperless_lines):
    nas = parse(nas_lines, ("sender_receipt", "scope", "source", "receiver_source", "sha256"), "NAS")
    imported = parse(paperless_lines, ("schema_version", "bridge_receipt", "receiver_source", "sha256", "document_id"), "PAPERLESS")
    by_receiver = {}
    for item in imported:
        dest = item["receiver_source"]
        if (item["schema_version"] != 1 or type(item["schema_version"]) is not int
                or not isinstance(dest, str) or dest in by_receiver
                or not BRIDGE_ID.fullmatch(item["bridge_receipt"])
                or not DIGEST.fullmatch(item["sha256"])
                or type(item["document_id"]) is not int or item["document_id"] <= 0):
            raise RuntimeError("INVALID_OR_DUPLICATE_PAPERLESS_PROOF")
        by_receiver[dest] = item
    seen = set()
    eligible = 0
    missing = []
    counts = {scope: [0, 0, 0] for scope in SCOPES}
    for item in nas:
        dest = item["receiver_source"]
        scope = item["scope"]
        name = item["source"]
        if (scope not in counts or not isinstance(name, str) or not name.lower().endswith(".pdf")
                or name in (".", "..") or "/" in name or "\\" in name
                or not isinstance(dest, str) or not dest.startswith(scope + "/")
                or dest in seen or not SENDER_ID.fullmatch(item["sender_receipt"])
                or not DIGEST.fullmatch(item["sha256"])):
            raise RuntimeError("INVALID_OR_DUPLICATE_NAS_RECORD")
        seen.add(dest)
        counts[scope][0] += 1
        proof = by_receiver.get(dest)
        if proof is None:
            missing.append(dest)
            counts[scope][2] += 1
        elif proof["sha256"] != item["sha256"]:
            raise RuntimeError("DIGEST_MISMATCH " + dest)
        else:
            eligible += 1
            counts[scope][1] += 1
            print("MATCH", scope, "document", proof["document_id"],
                  "bridge", proof["bridge_receipt"], "sender", item["sender_receipt"])
    print("NAS_SENT_VERIFIED", len(nas))
    print("PAPERLESS_LIVE_IMPORTED", len(imported))
    print("MATCHED", eligible)
    for scope, (sent, matched, absent) in counts.items():
        print("SCOPE_COUNTS", scope, "SENT", sent, "MATCHED", matched, "MISSING", absent)
    for dest in missing:
        print("BLOCKER MISSING_LIVE_IMPORT_PROOF", dest)
    print("MISSING_LIVE_IMPORT_PROOF", len(missing))
    if not nas:
        print("BLOCKER NO_NAS_SOURCES")
    print("ARCHIVE_MATCH_READY" if nas and not missing else "ARCHIVE_MATCH_BLOCKED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or set(data) != {"nas", "paperless"}:
        raise RuntimeError("INVALID_COMPARISON_INPUT")
    compare(data["nas"], data["paperless"])
