#!/usr/bin/env python3
"""Read-only diagnosis of one previously imported Paperless bridge receipt.

Does not infer a deletion from a missing filename; does not change any state.
"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
RECEIPT_ID = "7a92b91deb7b2e8e35f9f710.json"

DJANGO_INSPECT = """
import json
import os
from documents.models import Document
pk = int(os.environ["BP_DOCUMENT_ID"])
expected_name = os.environ["BP_EXPECTED_NAME"]
expected_sha = os.environ["BP_EXPECTED_SHA"]
expected_owner = os.environ["BP_EXPECTED_OWNER"]
doc = Document.objects.filter(pk=pk).select_related("owner").first()
result = {
    "document_id": pk,
    "exists": doc is not None,
    "original_filename_matches_receipt": None if doc is None else doc.original_filename == expected_name,
    "checksum_matches_receipt": None if doc is None else doc.checksum == expected_sha,
    "owner_matches_receipt": None if doc is None else (
        doc.owner is not None and doc.owner.username == expected_owner),
    "page_count": None if doc is None else doc.page_count,
    "root_document_id": None if doc is None else doc.root_document_id,
    "actual_original_filename": None if doc is None else doc.original_filename,
    "expected_filename_exists": Document.objects.filter(original_filename=expected_name).exists(),
}
print("BP_IMPORT_DIAGNOSTIC:" + json.dumps(result, ensure_ascii=True))
"""


def inspect(document_id, name, checksum, owner):
    env = os.environ.copy()
    env.update(BP_DOCUMENT_ID=str(document_id), BP_EXPECTED_NAME=name,
               BP_EXPECTED_SHA=checksum, BP_EXPECTED_OWNER=owner)
    command = ["podman", "exec", "-e", "BP_DOCUMENT_ID", "-e", "BP_EXPECTED_NAME",
               "-e", "BP_EXPECTED_SHA", "-e", "BP_EXPECTED_OWNER",
               "bergen-paperless", "python", "/usr/src/paperless/src/manage.py",
               "shell", "-c", DJANGO_INSPECT]
    proc = subprocess.run(command, env=env, text=True, capture_output=True,
                          timeout=90, check=False)
    if proc.returncode:
        raise RuntimeError("DOCUMENT_LOOKUP_FAILED")
    lines = [line.split("BP_IMPORT_DIAGNOSTIC:", 1)[1]
             for line in proc.stdout.splitlines()
             if line.startswith("BP_IMPORT_DIAGNOSTIC:")]
    if len(lines) != 1:
        raise RuntimeError("UNEXPECTED_DOCUMENT_LOOKUP")
    result = json.loads(lines[0])
    if type(result.get("document_id")) is not int or result["document_id"] != document_id:
        raise RuntimeError("UNEXPECTED_DOCUMENT_ID")
    return result


def main():
    if os.geteuid() != 0 or not RECONCILER.is_file() or RECONCILER.is_symlink():
        raise RuntimeError("RECONCILER_REQUIRED")
    spec = importlib.util.spec_from_file_location("bergen_reconciler_diagnostic", RECONCILER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    receipt, filename, (owner, group) = mod.load_receipt(mod.RECEIPTS / RECEIPT_ID)
    doc_id = receipt.get("document_id")
    if (receipt.get("status") != "IMPORTED" or type(doc_id) is not int
            or doc_id <= 0):
        raise RuntimeError("NOT_A_VALID_IMPORTED_RECEIPT")
    print("TARGET_RECEIPT", RECEIPT_ID)
    print("EXPECTED_DOCUMENT_ID", doc_id)
    print("EXPECTED_SCOPE", receipt["source"].rsplit("/", 1)[0])
    print("EXPECTED_OWNER", owner)
    print("EXPECTED_GROUP", group or "(private)")
    try:
        live = mod.verify(filename, receipt["sha256"], owner, group)
    except Exception as exc:
        print("LIVE_VERIFY_EXCEPTION", str(exc)[-900:])
        live = None
    else:
        print("LIVE_VERIFY", "PENDING_OR_FILENAME_CHANGED" if live is None else live)
    result = inspect(doc_id, filename, receipt["sha256"], owner)
    print("DOCUMENT_EXISTS", result["exists"])
    print("EXPECTED_FILENAME_EXISTS", result["expected_filename_exists"])
    if result["exists"]:
        print("ORIGINAL_FILENAME_MATCHES_RECEIPT", result["original_filename_matches_receipt"])
        print("CHECKSUM_MATCHES_RECEIPT", result["checksum_matches_receipt"])
        print("OWNER_MATCHES_RECEIPT", result["owner_matches_receipt"])
        print("PAGE_COUNT", result["page_count"])
        print("ROOT_DOCUMENT_ID", result["root_document_id"])
        if not result["original_filename_matches_receipt"]:
            print("ACTUAL_ORIGINAL_FILENAME", result["actual_original_filename"])
            if (result["checksum_matches_receipt"]
                    and result["owner_matches_receipt"]
                    and result["root_document_id"] is None):
                try:
                    renamed = mod.verify(result["actual_original_filename"],
                                         receipt["sha256"], owner, group)
                except Exception as exc:
                    print("RENAMED_FILENAME_LIVE_ACL_EXCEPTION", str(exc)[-900:])
                else:
                    print("RENAMED_FILENAME_LIVE_ACL_VERIFICATION",
                          "OK" if renamed == doc_id else "BLOCKED")
    print("DIAGNOSTIC_ONLY_NO_LIFECYCLE_DECISION")
    print("NO_FILES_CHANGED")


if __name__ == "__main__":
    main()
