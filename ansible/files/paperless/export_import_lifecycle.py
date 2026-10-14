#!/usr/bin/env python3
"""Read-only live Paperless import lifecycle exporter.

Every imported receipt is live-verified. Exactly one exception is permitted:
document 26 may be reported DELETED_BY_USER only with an exact, previously
published private journal, current NAS absence proof and fresh Paperless
absence verification. Other missing imports still fail closed.

Does not alter any receipt, document, journal, source or archive.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
EVENT = "f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26"
JOURNAL_SHA = "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a"
DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
BRIDGE = "1ebb2c1d26d7b1494d28d9cd.json"
SENDER = "7a9e41ee25d2a98c4e529472f3db2ab6c70b453a3214c1da537175bbcef1b4e8.json"
RECEIVER = "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf"
DJANGO_ABSENCE = """
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


def one(lines, marker=False):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_LIFECYCLE_EVIDENCE")
    entries = [x for x in lines.splitlines() if x.strip()]
    if len(entries) != (2 if marker else 1):
        raise RuntimeError("INVALID_LIFECYCLE_EVIDENCE_COUNT")
    if marker and entries[1] != "NO_FILES_CHANGED":
        raise RuntimeError("MISSING_READ_ONLY_EVIDENCE_MARKER")
    result = json.loads(entries[0])
    if not isinstance(result, dict):
        raise RuntimeError("INVALID_LIFECYCLE_EVIDENCE_OBJECT")
    return result


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def validate_proofs(data):
    if not isinstance(data, dict) or set(data) != {"journal", "deleted", "nas_deleted"}:
        raise RuntimeError("INVALID_LIFECYCLE_REQUEST")
    journal = one(data["journal"], marker=True)
    deleted = one(data["deleted"])
    nas = one(data["nas_deleted"], marker=True)
    if (hashlib.sha256(canonical(journal)).hexdigest() != JOURNAL_SHA
            or journal.get("event_id") != EVENT or journal.get("event") != "DELETED_BY_USER"
            or journal.get("document_id") != 26
            or journal.get("bridge_receipt") != BRIDGE
            or journal.get("sender_receipt") != SENDER
            or journal.get("sha256") != DIGEST
            or journal.get("receiver_source") != RECEIVER
            or journal.get("nas_original_absent") is not True
            or journal.get("paperless_document_absent") is not True
            or journal.get("original_filename_absent") is not True
            or deleted != {
                "schema_version": 1, "bridge_receipt": BRIDGE, "document_id": 26,
                "receiver_source": RECEIVER, "sha256": DIGEST,
                "proposed_status": "DELETED_IN_PAPERLESS",
                "live_document_absent": True, "original_filename_absent": True,
            }
            or nas != {
                "schema_version": 1, "sender_receipt": SENDER,
                "scope": "Privat/thomas", "source": "Gebuehren 2.pdf",
                "receiver_source": RECEIVER, "sha256": DIGEST,
                "sender_status": "SENT", "nas_original_absent": True,
            }):
        raise RuntimeError("UNAPPROVED_DELETED_BY_USER_PROOF")
    return journal


def verify_absence(mod, receipt, filename, owner, group):
    if (receipt.get("status") != "IMPORTED" or receipt.get("document_id") != 26
            or receipt.get("source") != RECEIVER or receipt.get("sha256") != DIGEST
            or owner != "thomas" or group):
        raise RuntimeError("DELETED_RECEIPT_IDENTITY_CHANGED")
    if mod.verify(filename, DIGEST, owner, group) is not None:
        raise RuntimeError("DELETED_DOCUMENT_STILL_LIVE")
    env = os.environ.copy()
    env.update(BP_DOC_ID="26", BP_EXPECTED_FILENAME=filename)
    cmd = ["podman", "exec", "-e", "BP_DOC_ID", "-e", "BP_EXPECTED_FILENAME",
           "bergen-paperless", "python", "/usr/src/paperless/src/manage.py",
           "shell", "-c", DJANGO_ABSENCE]
    result = subprocess.run(cmd, env=env, text=True, capture_output=True,
                            timeout=90, check=False)
    if result.returncode:
        raise RuntimeError("PAPERLESS_ABSENCE_QUERY_FAILED")
    lines = [x.split("BP_DELETION_LOOKUP:", 1)[1]
             for x in result.stdout.splitlines()
             if x.startswith("BP_DELETION_LOOKUP:")]
    if len(lines) != 1 or json.loads(lines[0]) != {
            "id_exists": False, "filename_exists": False}:
        raise RuntimeError("DELETED_DOCUMENT_OR_FILENAME_PRESENT")


def collect(data, mod):
    journal = validate_proofs(data)
    checked = 0
    deleted_seen = 0
    result = []
    for path in sorted(mod.RECEIPTS.glob("*.json")):
        receipt, filename, (owner, group) = mod.load_receipt(path)
        if receipt["status"] != "IMPORTED":
            continue
        rel = receipt["source"]
        basename = rel.rsplit("/", 1)[-1]
        found = re.search(r"--nas-([0-9a-f]{64})\.pdf$", basename)
        if found is None:
            continue
        if found.group(1) != receipt["sha256"]:
            raise RuntimeError("NAS_DIGEST_IN_FILENAME_MISMATCH " + path.name)
        docid = receipt.get("document_id")
        if type(docid) is not int or docid <= 0:
            raise RuntimeError("INVALID_IMPORTED_DOCUMENT_ID " + path.name)
        if path.name == BRIDGE:
            verify_absence(mod, receipt, filename, owner, group)
            if docid != journal["document_id"]:
                raise RuntimeError("DELETED_DOCUMENT_ID_CHANGED")
            deleted_seen += 1
            result.append({
                "schema_version": 1, "status": "DELETED_BY_USER",
                "bridge_receipt": path.name, "sender_receipt": SENDER,
                "receiver_source": rel, "sha256": receipt["sha256"],
                "document_id": docid,
            })
        else:
            live_id = mod.verify(filename, receipt["sha256"], owner, group)
            if live_id != docid:
                raise RuntimeError("LIVE_IMPORT_VERIFICATION_FAILED " + path.name)
            result.append({
                "schema_version": 1, "status": "IMPORTED",
                "bridge_receipt": path.name, "receiver_source": rel,
                "sha256": receipt["sha256"], "document_id": docid,
            })
        checked += 1
        if checked > 10000:
            raise RuntimeError("EVIDENCE_LIMIT_EXCEEDED")
    if deleted_seen != 1:
        raise RuntimeError("EXPECTED_ONE_DELETED_RECEIPT")
    return result


def main():
    if os.geteuid() != 0 or not RECONCILER.is_file() or RECONCILER.is_symlink():
        raise RuntimeError("EXPECTED_PAPERLESS_RECONCILER_REQUIRED")
    data = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("bergen_reconcile_read_only", RECONCILER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    records = collect(data, mod)
    for record in records:
        print(json.dumps(record, sort_keys=True, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
