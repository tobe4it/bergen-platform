#!/usr/bin/env python3
"""Read-only evidence for an explicitly acknowledged deletion.

Does not change Paperless, the bridge receipt, or the NAS. In particular,
it does not mark a receipt deleted; the state is only a proposed transition.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
BRIDGE_ID = re.compile(r"[a-f0-9]{24}\\.json\\Z")
DJANGO_CHECK = """
import json
import os
from documents.models import Document
pk = int(os.environ["BP_DOC_ID"])
filename = os.environ["BP_EXPECTED_FILENAME"]
print("BP_DELETION_LOOKUP:" + json.dumps({
    "id_exists": Document.objects.filter(pk=pk).exists(),
    "filename_exists": Document.objects.filter(original_filename=filename).exists(),
}))
"""


def main(receipt_name, document_id):
    if os.geteuid() != 0 or not BRIDGE_ID.fullmatch(receipt_name):
        raise RuntimeError("INVALID_OPERATOR_TARGET")
    if document_id <= 0 or not RECONCILER.is_file() or RECONCILER.is_symlink():
        raise RuntimeError("INVALID_DOCUMENT_ID_OR_RECONCILER")
    spec = importlib.util.spec_from_file_location("bergen_reconcile_read_only", RECONCILER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    receipt, expected_filename, (owner, group) = mod.load_receipt(mod.RECEIPTS / receipt_name)
    if (receipt["status"] != "IMPORTED" or receipt.get("document_id") != document_id
            or not receipt["source"].startswith("Privat/thomas/") or owner != "thomas" or group):
        raise RuntimeError("DELETION_TARGET_NOT_APPROVED_SCOPE")
    # If the original filename still exists, the existing live verifier must
    # validate it; a missing or inconsistent import is NOT proof of deletion.
    if mod.verify(expected_filename, receipt["sha256"], owner, group) is not None:
        raise RuntimeError("DOCUMENT_STILL_VERIFIED_LIVE")
    env = os.environ.copy()
    env.update(BP_DOC_ID=str(document_id), BP_EXPECTED_FILENAME=expected_filename)
    cmd = ["podman", "exec", "-e", "BP_DOC_ID", "-e", "BP_EXPECTED_FILENAME",
           "bergen-paperless", "python", "/usr/src/paperless/src/manage.py",
           "shell", "-c", DJANGO_CHECK]
    result = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=90, check=False)
    if result.returncode:
        raise RuntimeError("PAPERLESS_LOOKUP_FAILED " + (result.stderr + result.stdout)[-500:])
    lines = [line.split("BP_DELETION_LOOKUP:", 1)[1] for line in result.stdout.splitlines()
             if line.startswith("BP_DELETION_LOOKUP:")]
    if len(lines) != 1:
        raise RuntimeError("UNEXPECTED_PAPERLESS_LOOKUP")
    proof = json.loads(lines[0])
    if proof != {"id_exists": False, "filename_exists": False}:
        raise RuntimeError("DOCUMENT_ORIGINAL_FILENAME_STILL_PRESENT")
    print(json.dumps({
        "schema_version": 1,
        "bridge_receipt": receipt_name,
        "document_id": document_id,
        "receiver_source": receipt["source"],
        "sha256": receipt["sha256"],
        "proposed_status": "DELETED_IN_PAPERLESS",
        "live_document_absent": True,
        "original_filename_absent": True,
    }, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 3 or not sys.argv[2].isdigit():
        raise SystemExit("usage: ... BRIDGE_RECEIPT DOCUMENT_ID")
    main(sys.argv[1], int(sys.argv[2]))
