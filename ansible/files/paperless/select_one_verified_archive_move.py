#!/usr/bin/env python3
"""Strict controller join for ONE read-only/opt-in Synology archive operation.

Input: {nas: JSONL from live NAS audit under sync.lock,
        paperless: JSONL from independent live LXC exporter, only: Scope/Name.pdf}.
Output: exactly one JSON proof for the separate manual/archive worker.
The generated fields must be carried directly from verified controller probes.
No archival, no NAS or Paperless access in this script.
"""
import json
import re
import sys

SCOPES = ("Familie", "Eltern", "Privat/thomas", "Privat/nadja")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
RECEIPT = re.compile(r"[a-f0-9]{64}\.json\Z")
BRIDGE = re.compile(r"[a-f0-9]{24}\.json\Z")
MAX = 10000


def parse_jsonl(raw, keys):
    if not isinstance(raw, str) or len(raw) > 8 * 1024 * 1024:
        raise RuntimeError("INVALID_ARCHIVE_SOURCE_EVIDENCE")
    out = []
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value:
                raise ValueError("DUPLICATE_EVIDENCE_KEY")
            value[k] = v
        return value
    for line in raw.splitlines():
        if not line.strip():
            continue
        item = json.loads(line, object_pairs_hook=unique)
        if not isinstance(item, dict) or set(item) != set(keys):
            raise RuntimeError("INVALID_ARCHIVE_EVIDENCE_RECORD")
        out.append(item)
        if len(out) > MAX:
            raise RuntimeError("ARCHIVE_EVIDENCE_LIMIT")
    return out


def select_one(nas, paperless, only):
    if (not isinstance(only, str) or not any(
            only.startswith(scope + "/") and
            "/" not in only[len(scope) + 1:] and
            only[len(scope) + 1:].lower().endswith(".pdf") and
            only[len(scope) + 1:] not in ("", ".", "..")
            for scope in SCOPES)):
        raise ValueError("INVALID_EXACT_ARCHIVE_SELECTION")
    sent = parse_jsonl(nas, ("sender_receipt", "scope", "source",
                            "receiver_source", "sha256"))
    live = parse_jsonl(paperless, ("schema_version", "bridge_receipt",
                                 "receiver_source", "sha256", "document_id"))
    sender_by_dest, source_ident = {}, set()
    for item in sent:
        scope, name, dest = item["scope"], item["source"], item["receiver_source"]
        if (scope not in SCOPES or not isinstance(name, str)
                or not name.lower().endswith(".pdf")
                or "/" in name or "\\" in name
                or not isinstance(dest, str) or not dest.startswith(scope + "/")
                or (scope, name) in source_ident or dest in sender_by_dest
                or not isinstance(item["sender_receipt"], str)
                or not RECEIPT.fullmatch(item["sender_receipt"])
                or not isinstance(item["sha256"], str)
                or not DIGEST.fullmatch(item["sha256"])):
            raise RuntimeError("INVALID_NAS_ARCHIVE_INVENTORY")
        sender_by_dest[dest] = item
        source_ident.add((scope, name))
    live_by_dest = {}
    for item in live:
        dest = item["receiver_source"]
        if (type(item["schema_version"]) is not int or item["schema_version"] != 1
                or not isinstance(dest, str) or dest in live_by_dest
                or not isinstance(item["bridge_receipt"], str)
                or not BRIDGE.fullmatch(item["bridge_receipt"])
                or not isinstance(item["sha256"], str)
                or not DIGEST.fullmatch(item["sha256"])
                or type(item["document_id"]) is not int or item["document_id"] <= 0):
            raise RuntimeError("INVALID_LIVE_IMPORT_INVENTORY")
        live_by_dest[dest] = item
    matches = [
        item for item in sent if item["scope"] + "/" + item["source"] == only
    ]
    if len(matches) != 1:
        raise RuntimeError("EXACT_SENDER_RECEIPT_NOT_FOUND")
    sender = matches[0]
    imported = live_by_dest.get(sender["receiver_source"])
    if imported is None or imported["sha256"] != sender["sha256"]:
        raise RuntimeError("LIVE_IMPORT_NOT_MATCHED")
    return {
        "schema_version": 1, "sender_receipt": sender["sender_receipt"],
        "bridge_receipt": imported["bridge_receipt"],
        "receiver_source": sender["receiver_source"],
        "sha256": sender["sha256"], "document_id": imported["document_id"],
    }


def main():
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or set(data) != {"nas", "paperless", "only"}:
        raise RuntimeError("ARCHIVE_CONTROLLER_INPUT_SCHEMA")
    print(json.dumps(select_one(data["nas"], data["paperless"], data["only"]),
                     ensure_ascii=True, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        print("ARCHIVE_CONTROLLER_SELECTION_FAILED",
              str(exc).split(" ", 1)[0], file=sys.stderr)
        sys.exit(1)
