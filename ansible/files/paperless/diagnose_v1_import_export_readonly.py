#!/usr/bin/env python3
"""READ-ONLY classification of the live Paperless v1 IMPORTED export failure.

Always emits allowlisted status markers only. Never emit exception strings,
tracebacks, PDF filenames, receipt IDs, paths, hashes or document IDs.
No mutating operations, no journal acknowledgement, no archive operations.
Only a single pass of the same live verification used by the v1 exporter.
"""
import importlib.util
import re
import sys
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
NAS_V1 = re.compile(r"--nas-([0-9a-f]{64})\.pdf\Z")
MAX_RECORDS = 10000


class DiagnosticFailure(RuntimeError):
    pass


def fail(code):
    raise DiagnosticFailure(code)


def _load():
    try:
        if not RECONCILER.is_file() or RECONCILER.is_symlink():
            fail("RECONCILER_MISSING_OR_UNSAFE")
        spec = importlib.util.spec_from_file_location(
            "bergen_reconciler_diag", str(RECONCILER))
        if spec is None or spec.loader is None:
            fail("RECONCILER_CANNOT_LOAD")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except DiagnosticFailure:
        raise
    except BaseException:
        fail("RECONCILER_IMPORT_ERROR")


def diagnose(mod):
    counts = {"bridge_receipts": 0, "imported_receipts": 0,
              "nas_v1_receipts": 0, "verified_v1_imports": 0}
    try:
        paths = sorted(mod.RECEIPTS.glob("*.json"))
    except BaseException:
        fail("BRIDGE_DIRECTORY_READ_FAILED")
    if len(paths) > MAX_RECORDS:
        fail("BRIDGE_RECEIPT_LIMIT_EXCEEDED")
    for path in paths:
        counts["bridge_receipts"] += 1
        try:
            record, document_name, route = mod.load_receipt(path)
        except BaseException:
            fail("BRIDGE_RECEIPT_READ_OR_SCHEMA_FAILED")
        if not isinstance(record, dict):
            fail("BRIDGE_RECEIPT_READ_OR_SCHEMA_FAILED")
        if record.get("status") != "IMPORTED":
            continue
        counts["imported_receipts"] += 1
        source = record.get("source")
        if not isinstance(source, str):
            fail("IMPORTED_SOURCE_MALFORMED")
        basename = source.rsplit("/", 1)[-1]
        matched = NAS_V1.search(basename)
        if matched is None:
            continue
        counts["nas_v1_receipts"] += 1
        if (not isinstance(record.get("sha256"), str)
                or matched.group(1) != record.get("sha256")):
            fail("IMPORTED_SENDER_DIGEST_MISMATCH")
        document_id = record.get("document_id")
        if type(document_id) is not int or document_id <= 0:
            fail("IMPORTED_DOCUMENT_ID_INVALID")
        try:
            owner, group = route
            verified_id = mod.verify(document_name, record["sha256"], owner, group)
        except BaseException:
            fail("PAPERLESS_LIVE_VERIFICATION_FAILED")
        # The existing reconciler returns None when the original filename
        # has no matching Paperless document. That is materially different
        # from a *different* positive document ID, including after a user
        # intentionally removed an already imported document.
        if verified_id is None:
            fail("PAPERLESS_DOCUMENT_NOT_FOUND")
        if type(verified_id) is not int or verified_id <= 0:
            fail("PAPERLESS_VERIFIER_INVALID_RESULT")
        if verified_id != document_id:
            fail("PAPERLESS_DOCUMENT_ID_MISMATCH")
        counts["verified_v1_imports"] += 1
    return counts


def main():
    try:
        result = diagnose(_load())
    except DiagnosticFailure as exc:
        # DiagnosticFailure is created only from fixed codes in this module.
        print("V1_EXPORT_DIAGNOSTIC_BLOCKED", exc)
    except BaseException:
        print("V1_EXPORT_DIAGNOSTIC_BLOCKED", "UNCLASSIFIED_READONLY_ERROR")
    else:
        for name, count in result.items():
            print("V1_" + name.upper(), count)
        print("V1_EXPORT_DIAGNOSTIC_OK")
    print("NO_FILES_CHANGED")
    print("ARCHIVE_NOT_AUTHORIZED")
    print("PURGE_NOT_AUTHORIZED")


if __name__ == "__main__":
    main()
