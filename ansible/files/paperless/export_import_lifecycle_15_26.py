#!/usr/bin/env python3
"""Read-only Paperless import lifecycle export with exactly two pinned deletions.

Documents 15 and 26 must each have independently verified private v2 journal,
fresh live Paperless absence and historical Synology SENT receipt/absence.
Every other IMPORTED receipt is live verified; unknown deletion fails closed.
No file, receipt, archive or document writes.
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
DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
DELETIONS = {
    15: {
        "event_id": "2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90",
        "journal_sha": "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b",
        "bridge_receipt": "7a92b91deb7b2e8e35f9f710.json",
        "sender_receipt": "adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json",
        "source": "Gebuehren.pdf",
        "receiver_source": "Privat/thomas/Gebuehren--nas-" + DIGEST + ".pdf",
    },
    26: {
        "event_id": "f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26",
        "journal_sha": "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a",
        "bridge_receipt": "1ebb2c1d26d7b1494d28d9cd.json",
        "sender_receipt": "7a9e41ee25d2a98c4e529472f3db2ab6c70b453a3214c1da537175bbcef1b4e8.json",
        "source": "Gebuehren 2.pdf",
        "receiver_source": "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf",
    },
}
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


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def one(lines, marker=False):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_LIFECYCLE_EVIDENCE_STREAM")
    entries = [line for line in lines.splitlines() if line.strip()]
    if len(entries) != (2 if marker else 1) or (marker and entries[-1] != "NO_FILES_CHANGED"):
        raise RuntimeError("INVALID_LIFECYCLE_EVIDENCE_COUNT")
    value = json.loads(entries[0])
    if not isinstance(value, dict):
        raise RuntimeError("INVALID_LIFECYCLE_EVIDENCE_OBJECT")
    return value


def journals(lines):
    if not isinstance(lines, str):
        raise RuntimeError("INVALID_JOURNAL_STREAM")
    entries = [line for line in lines.splitlines() if line.strip()]
    if len(entries) != 3 or entries[-1] != "NO_FILES_CHANGED":
        raise RuntimeError("REQUIRE_EXACTLY_TWO_VERIFIED_JOURNALS")
    values = [json.loads(line) for line in entries[:-1]]
    if not all(isinstance(x, dict) for x in values):
        raise RuntimeError("INVALID_JOURNAL_OBJECT")
    by_id = {}
    for value in values:
        docid = value.get("document_id")
        if type(docid) is not int or docid in by_id:
            raise RuntimeError("DUPLICATE_OR_UNKNOWN_JOURNAL")
        by_id[docid] = value
    if set(by_id) != set(DELETIONS):
        raise RuntimeError("MISSING_OR_UNKNOWN_DELETION_JOURNAL")
    return by_id


def validate_proofs(data):
    if not isinstance(data, dict) or set(data) != {
            "journal", "deleted_15", "deleted_26", "nas_deleted_15", "nas_deleted_26"}:
        raise RuntimeError("INVALID_DUAL_LIFECYCLE_REQUEST")
    by_id = journals(data["journal"])
    for docid, spec in DELETIONS.items():
        record = by_id[docid]
        deleted = one(data["deleted_" + str(docid)])
        nas = one(data["nas_deleted_" + str(docid)], marker=True)
        expected_deleted = {
            "schema_version": 1, "bridge_receipt": spec["bridge_receipt"],
            "document_id": docid, "receiver_source": spec["receiver_source"],
            "sha256": DIGEST, "proposed_status": "DELETED_IN_PAPERLESS",
            "live_document_absent": True, "original_filename_absent": True,
        }
        expected_nas = {
            "schema_version": 1, "sender_receipt": spec["sender_receipt"],
            "scope": "Privat/thomas", "source": spec["source"],
            "receiver_source": spec["receiver_source"], "sha256": DIGEST,
            "sender_status": "SENT", "nas_original_absent": True,
        }
        expected_fields = {
            "schema_version": 2, "event": "DELETED_BY_USER",
            "event_id": spec["event_id"], "document_id": docid,
            "bridge_receipt": spec["bridge_receipt"],
            "sender_receipt": spec["sender_receipt"],
            "scope": "Privat/thomas", "source": spec["source"],
            "receiver_source": spec["receiver_source"], "sha256": DIGEST,
            "sender_status": "SENT", "nas_original_absent": True,
            "paperless_document_absent": True, "original_filename_absent": True,
            "confirmed_by": "thomas", "confirmation_method": "explicit_user_chat",
            "confirmation_date": "2026-10-14",
            "decision_reason": "explicit_deletion_on_paperless_and_nas",
        }
        if (hashlib.sha256(canonical(record)).hexdigest() != spec["journal_sha"]
                or record != expected_fields or deleted != expected_deleted
                or nas != expected_nas):
            raise RuntimeError("UNAPPROVED_DELETED_BY_USER_PROOF " + str(docid))
    return by_id


def verify_absence(mod, receipt, filename, owner, group, docid):
    spec = DELETIONS[docid]
    if (receipt.get("status") != "IMPORTED"
            or receipt.get("document_id") != docid
            or receipt.get("source") != spec["receiver_source"]
            or receipt.get("sha256") != DIGEST
            or owner != "thomas" or group):
        raise RuntimeError("DELETED_RECEIPT_IDENTITY_CHANGED " + str(docid))
    if mod.verify(filename, DIGEST, owner, group) is not None:
        raise RuntimeError("DELETED_DOCUMENT_STILL_LIVE " + str(docid))
    env = os.environ.copy()
    env.update(BP_DOC_ID=str(docid), BP_EXPECTED_FILENAME=filename)
    cmd = ["podman", "exec", "-e", "BP_DOC_ID", "-e", "BP_EXPECTED_FILENAME",
           "bergen-paperless", "python", "/usr/src/paperless/src/manage.py",
           "shell", "-c", DJANGO_ABSENCE]
    response = subprocess.run(cmd, env=env, text=True, capture_output=True,
                              timeout=90, check=False)
    if response.returncode:
        raise RuntimeError("PAPERLESS_ABSENCE_QUERY_FAILED " + str(docid))
    lines = [line.split("BP_DELETION_LOOKUP:", 1)[1]
             for line in response.stdout.splitlines()
             if line.startswith("BP_DELETION_LOOKUP:")]
    if len(lines) != 1 or json.loads(lines[0]) != {
            "id_exists": False, "filename_exists": False}:
        raise RuntimeError("DELETED_DOCUMENT_OR_FILENAME_PRESENT " + str(docid))


def collect(data, mod):
    validate_proofs(data)
    deleted_by_bridge = {spec["bridge_receipt"]: docid
                         for docid, spec in DELETIONS.items()}
    checked = 0
    deleted_seen = set()
    results = []
    for path in sorted(mod.RECEIPTS.glob("*.json")):
        receipt, filename, (owner, group) = mod.load_receipt(path)
        if receipt["status"] != "IMPORTED":
            continue
        rel = receipt["source"]
        found = re.search(r"--nas-([0-9a-f]{64})\.pdf$", rel.rsplit("/", 1)[-1])
        if found is None:
            continue
        if found.group(1) != receipt["sha256"]:
            raise RuntimeError("NAS_DIGEST_IN_FILENAME_MISMATCH " + path.name)
        docid = receipt.get("document_id")
        if type(docid) is not int or docid <= 0:
            raise RuntimeError("INVALID_IMPORTED_DOCUMENT_ID " + path.name)
        if path.name in deleted_by_bridge:
            expected_id = deleted_by_bridge[path.name]
            if docid != expected_id or expected_id in deleted_seen:
                raise RuntimeError("DELETED_RECEIPT_IDENTITY_CHANGED " + path.name)
            verify_absence(mod, receipt, filename, owner, group, expected_id)
            spec = DELETIONS[expected_id]
            deleted_seen.add(expected_id)
            results.append({
                "schema_version": 1, "status": "DELETED_BY_USER",
                "bridge_receipt": path.name, "sender_receipt": spec["sender_receipt"],
                "receiver_source": rel, "sha256": receipt["sha256"],
                "document_id": docid,
            })
        else:
            live_id = mod.verify(filename, receipt["sha256"], owner, group)
            if live_id != docid:
                raise RuntimeError("LIVE_IMPORT_VERIFICATION_FAILED " + path.name)
            results.append({
                "schema_version": 1, "status": "IMPORTED",
                "bridge_receipt": path.name, "receiver_source": rel,
                "sha256": receipt["sha256"], "document_id": docid,
            })
        checked += 1
        if checked > 10000:
            raise RuntimeError("EVIDENCE_LIMIT_EXCEEDED")
    if deleted_seen != set(DELETIONS):
        raise RuntimeError("EXPECTED_TWO_DELETED_RECEIPTS")
    return results


def main():
    if os.geteuid() != 0 or not RECONCILER.is_file() or RECONCILER.is_symlink():
        raise RuntimeError("EXPECTED_PAPERLESS_RECONCILER_REQUIRED")
    data = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("bergen_reconcile_read_only", RECONCILER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for record in collect(data, mod):
        print(json.dumps(record, sort_keys=True, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
