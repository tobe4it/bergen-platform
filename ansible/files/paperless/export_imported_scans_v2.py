#!/usr/bin/env python3
"""READ-ONLY: emit independently live-verified Paperless v2 imported documents.

Stream this script into Paperless LXC as root using the existing controlled
Proxmox path. Never accepts NAS evidence directly or approves archive/delete.
A v2 filename's trailing hash is a receipt-identity hash, NOT the PDF digest.
"""
import importlib.util
import json
import re
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
V2_NAME = re.compile(r"nas-(v2-[0-9a-f]{32}-[0-9a-f]{64})\.pdf\Z")
SCOPES = frozenset(("Privat/thomas", "Privat/nadja", "Eltern", "Familie"))
BRIDGE = re.compile(r"[0-9a-f]{24}\.json\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_RECORDS = 10000


def load_reconciler():
    if not RECONCILER.is_file():
        raise RuntimeError("PAPERLESS_RECONCILER_MISSING")
    spec = importlib.util.spec_from_file_location("bergen_reconciler", str(RECONCILER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(mod):
    """Return only documents whose live object, owner and ACL all verify."""
    items = []
    seen = set()
    for path in sorted(mod.RECEIPTS.glob("*.json")):
        receipt, document_name, (owner, group) = mod.load_receipt(path)
        if receipt["status"] != "IMPORTED":
            continue
        source = receipt["source"]
        if not isinstance(source, str):
            raise RuntimeError("INVALID_BRIDGE_SOURCE")
        scope, slash, basename = source.rpartition("/")
        if not slash or scope not in SCOPES:
            # Legacy or unrelated receipts are outside this v2 export.
            continue
        match = V2_NAME.fullmatch(basename)
        if match is None:
            continue
        if not BRIDGE.fullmatch(path.name):
            raise RuntimeError("INVALID_BRIDGE_RECEIPT_ID")
        sha = receipt["sha256"]
        document_id = receipt["document_id"]
        if (not isinstance(sha, str) or not SHA.fullmatch(sha)
                or type(document_id) is not int or document_id <= 0
                or source in seen):
            raise RuntimeError("INVALID_OR_DUPLICATE_V2_IMPORT_PROOF")
        seen.add(source)
        live_id = mod.verify(document_name, sha, owner, group)
        if live_id != document_id:
            raise RuntimeError("V2_LIVE_IMPORT_ACL_PROOF_FAILED")
        items.append({
            "schema_version": 2, "status": "IMPORTED",
            "bridge_receipt": path.name, "receiver_source": source,
            "receipt_id": match.group(1), "sha256": sha,
            "document_id": document_id,
        })
        if len(items) > MAX_RECORDS:
            raise RuntimeError("V2_IMPORT_PROOF_LIMIT_EXCEEDED")
    return items


def main():
    for item in collect(load_reconciler()):
        print(json.dumps(item, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":")), flush=True)
    print("V2_LIVE_IMPORT_AUDIT_COMPLETE")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("SOURCE_DELETE_NOT_AUTHORIZED")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    main()
