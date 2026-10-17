#!/usr/bin/env python3
"""Emit live-verified NAS scan import evidence as JSON Lines.

Read-only. Run as root INSIDE the Paperless LXC through the existing
bp-controller -> venombox -> pct exec control path. The output must be
delivered directly to a separately authorised NAS archive dry-run.
"""
import importlib.util
import json
import re
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
MAX_RECORDS = 10000


def load_reconciler():
    if not RECONCILER.is_file():
        raise RuntimeError("PAPERLESS_RECONCILER_MISSING")
    spec = importlib.util.spec_from_file_location("bergen_reconciler", str(RECONCILER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    mod = load_reconciler()
    checked = 0
    for path in sorted(mod.RECEIPTS.glob("*.json")):
        receipt, name, (owner, group) = mod.load_receipt(path)
        if receipt["status"] != "IMPORTED":
            continue

        # Exclude pre-bridge/other ingestion paths. Only the NAS sender
        # suffix is suitable for matching an independent NAS SENT receipt.
        rel = receipt["source"]
        basename = rel.rsplit("/", 1)[-1]
        found = re.search(r"--nas-([0-9a-f]{64})\.pdf$", basename)
        if found is None:
            continue
        if found.group(1) != receipt["sha256"]:
            raise RuntimeError("NAS_DIGEST_IN_FILENAME_MISMATCH " + path.name)

        document_id = receipt.get("document_id")
        if type(document_id) is not int or document_id <= 0:
            raise RuntimeError("INVALID_IMPORTED_DOCUMENT_ID " + path.name)
        live_id = mod.verify(name, receipt["sha256"], owner, group)
        if live_id != document_id:
            raise RuntimeError("LIVE_IMPORT_VERIFICATION_FAILED " + path.name)

        checked += 1
        if checked > MAX_RECORDS:
            raise RuntimeError("EVIDENCE_LIMIT_EXCEEDED")
        print(json.dumps({
            "schema_version": 1,
            "bridge_receipt": path.name,
            "receiver_source": rel,
            "sha256": receipt["sha256"],
            "document_id": document_id,
        }, sort_keys=True, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
