#!/usr/bin/env python3
"""Read-only, single-receipt Paperless verification diagnostic.

No receipt mutation, no document edits, no archive operations.
"""
import importlib.util
import os
import re
import stat
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
RECEIPT_ID = "1ebb2c1d26d7b1494d28d9cd.json"
EXPECTED_DOCUMENT = 26


def main():
    if os.geteuid() != 0:
        raise RuntimeError("ROOT_REQUIRED")
    if not RECONCILER.is_file() or RECONCILER.is_symlink():
        raise RuntimeError("RECONCILER_MISSING_OR_SYMLINK")
    spec = importlib.util.spec_from_file_location("bergen_reconciler_diagnostic", str(RECONCILER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = mod.RECEIPTS / RECEIPT_ID
    receipt, name, (owner, group) = mod.load_receipt(path)
    if receipt.get("status") != "IMPORTED" or receipt.get("document_id") != EXPECTED_DOCUMENT:
        raise RuntimeError("UNEXPECTED_RECEIPT_STATE_OR_DOCUMENT_ID")
    if receipt.get("source", "").split("/", 1)[0] != "Privat":
        raise RuntimeError("UNEXPECTED_SCOPE")
    print("TARGET_RECEIPT", RECEIPT_ID)
    print("EXPECTED_DOCUMENT_ID", EXPECTED_DOCUMENT)
    print("EXPECTED_OWNER", owner)
    print("EXPECTED_GROUP", group or "(private)")
    try:
        live_id = mod.verify(name, receipt["sha256"], owner, group)
    except Exception as exc:
        # Existing reconciler exposes the precise failed assertion, including
        # effective ACL mismatch. Do not suppress a genuine verification error.
        print("LIVE_VERIFY_EXCEPTION", str(exc)[-1200:])
        print("DIAGNOSTIC_BLOCKED")
        print("NO_FILES_CHANGED")
        return
    if live_id is None:
        print("LIVE_VERIFY_PENDING_OR_FILENAME_CHANGED")
        print("DIAGNOSTIC_BLOCKED")
    elif live_id != EXPECTED_DOCUMENT:
        print("LIVE_VERIFY_DIFFERENT_DOCUMENT", live_id)
        print("DIAGNOSTIC_BLOCKED")
    else:
        print("LIVE_VERIFY_OK", live_id)
        print("DIAGNOSTIC_OK")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    main()
