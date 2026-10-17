#!/usr/bin/env python3
"""Read-only, single-receipt Paperless verification diagnostic.

No receipt mutation, no document edits, no archive operations.
"""
import importlib.util
import os
import json
import subprocess
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
RECEIPT_ID = "1ebb2c1d26d7b1494d28d9cd.json"
EXPECTED_DOCUMENT = 26

DJANGO_INSPECT = """
import json
import os
from documents.models import Document
pk = int(os.environ["BP_DOCUMENT_ID"])
expected_name = os.environ["BP_EXPECTED_NAME"]
expected_sha = os.environ["BP_EXPECTED_SHA"]
expected_owner = os.environ["BP_EXPECTED_OWNER"]
doc = Document.objects.filter(pk=pk).select_related("owner").first()
if doc is None:
    result = {"exists": False, "document_id": pk}
else:
    result = {
        "exists": True,
        "document_id": pk,
        "actual_original_filename": doc.original_filename,
        "filename_matches_receipt": doc.original_filename == expected_name,
        "checksum_matches_receipt": doc.checksum == expected_sha,
        "owner_matches_receipt": doc.owner is not None and doc.owner.username == expected_owner,
        "page_count": doc.page_count,
        "root_document_id": doc.root_document_id,
    }
print("BP_DOCUMENT_DIAGNOSTIC:" + json.dumps(result, ensure_ascii=True))
"""


def inspect_document(name, checksum, owner):
    env = os.environ.copy()
    env.update(
        BP_DOCUMENT_ID=str(EXPECTED_DOCUMENT),
        BP_EXPECTED_NAME=name,
        BP_EXPECTED_SHA=checksum,
        BP_EXPECTED_OWNER=owner,
    )
    command = [
        "podman", "exec",
        "-e", "BP_DOCUMENT_ID", "-e", "BP_EXPECTED_NAME",
        "-e", "BP_EXPECTED_SHA", "-e", "BP_EXPECTED_OWNER",
        "bergen-paperless", "python", "/usr/src/paperless/src/manage.py",
        "shell", "-c", DJANGO_INSPECT,
    ]
    proc = subprocess.run(command, env=env, text=True, capture_output=True, timeout=90, check=False)
    if proc.returncode:
        raise RuntimeError("DOCUMENT_LOOKUP_FAILED " + (proc.stderr + proc.stdout)[-1200:])
    lines = [line[len("BP_DOCUMENT_DIAGNOSTIC:"):] for line in proc.stdout.splitlines()
             if line.startswith("BP_DOCUMENT_DIAGNOSTIC:")]
    if len(lines) != 1:
        raise RuntimeError("DOCUMENT_LOOKUP_UNEXPECTED_OUTPUT")
    result = json.loads(lines[0])
    if result.get("document_id") != EXPECTED_DOCUMENT:
        raise RuntimeError("DOCUMENT_LOOKUP_WRONG_ID")
    return result


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
        result = inspect_document(name, receipt["sha256"], owner)
        print("DOCUMENT_26_EXISTS", result["exists"])
        if result["exists"]:
            print("DOCUMENT_26_ORIGINAL_FILENAME", result["actual_original_filename"])
            print("DOCUMENT_26_FILENAME_MATCHES_RECEIPT", result["filename_matches_receipt"])
            print("DOCUMENT_26_SHA256_MATCHES_RECEIPT", result["checksum_matches_receipt"])
            print("DOCUMENT_26_OWNER_MATCHES_RECEIPT", result["owner_matches_receipt"])
            print("DOCUMENT_26_PAGE_COUNT", result["page_count"])
            print("DOCUMENT_26_ROOT_DOCUMENT_ID", result["root_document_id"])
            if (not result["filename_matches_receipt"]
                    and result["checksum_matches_receipt"]
                    and result["owner_matches_receipt"]
                    and result["root_document_id"] is None):
                try:
                    renamed_id = mod.verify(result["actual_original_filename"], receipt["sha256"], owner, group)
                    print("RENAMED_FILENAME_LIVE_ACL_VERIFICATION", "OK" if renamed_id == EXPECTED_DOCUMENT else "BLOCKED")
                except Exception as exc:
                    print("RENAMED_FILENAME_LIVE_ACL_EXCEPTION", str(exc)[-1200:])
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
