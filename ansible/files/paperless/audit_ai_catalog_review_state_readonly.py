"""Bounded, read-only diagnosis for one failed Paperless AI catalogue write.

Executed with Django 3.3.0 manage.py shell -c. The source is installed
via Ansible lookup and ends with an explicit main() invocation.
No OCR/title/filenames/owner/tag IDs, journal JSON or exception messages
are emitted. No classification, writes, PRAGMA migrations or journal fix.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import sys

FRAME = "BERGEN_PAPERLESS_CATALOG_REVIEW_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
STATES = {"PROCESSING", "REQUIRES_REVIEW", "APPLIED", "ROLLED_BACK"}
SNAPSHOT_KEYS = {
    "id", "owner_id", "title", "original_filename", "correspondent_id",
    "document_type_id", "storage_path_id", "created", "modified",
    "checksum", "content_sha256", "tag_ids", "inbox",
}
DIFFS = (
    ("title", "TITLE"), ("correspondent_id", "CORRESPONDENT"),
    ("document_type_id", "DOCUMENT_TYPE"), ("tag_ids", "TAGS"),
    ("owner_id", "OWNER"), ("storage_path_id", "STORAGE_PATH"),
    ("content_sha256", "OCR"), ("checksum", "FILE_CHECKSUM"),
    ("original_filename", "FILENAME"), ("created", "CREATED"),
    ("modified", "MODIFIED"), ("inbox", "INBOX"),
)


def report(**values):
    print(FRAME + json.dumps(dict(
        AUDIT="READ_ONLY", CHANGED=False,
        DOCUMENTS_CHANGED="NO", MODEL_INFERENCE="NO", **values
    ), sort_keys=True), flush=True)


def live_snapshot(doc):
    return {
        "id": doc.pk,
        "owner_id": doc.owner_id,
        "title": doc.title,
        "original_filename": doc.original_filename or "",
        "correspondent_id": doc.correspondent_id,
        "document_type_id": doc.document_type_id,
        "storage_path_id": doc.storage_path_id,
        "created": doc.created.isoformat(),
        "modified": doc.modified.isoformat(),
        "checksum": doc.checksum,
        "content_sha256": hashlib.sha256((doc.content or "").encode()).hexdigest(),
        "tag_ids": sorted(doc.tags.values_list("id", flat=True)),
        "inbox": doc.tags.filter(is_inbox_tag=True).exists(),
    }


def compare(before, after, expected_id):
    if (not isinstance(before, dict) or set(before) != SNAPSHOT_KEYS
            or before.get("id") != expected_id
            or not isinstance(before.get("tag_ids"), list)
            or not isinstance(after, dict) or set(after) != SNAPSHOT_KEYS):
        return "UNVERIFIED", "UNVERIFIED", "UNVERIFIED"
    diffs = [label for key, label in DIFFS if before[key] != after[key]]
    if before["id"] != after["id"]:
        return "UNVERIFIED", "UNVERIFIED", "UNVERIFIED"
    if not diffs:
        return "MATCH", "NONE", "PRESENT" if after["inbox"] else "ABSENT"
    if diffs == ["MODIFIED"]:
        return "DIFF", "MODIFIED_ONLY", "PRESENT" if after["inbox"] else "ABSENT"
    return "DIFF", "OTHER_FIELDS", "PRESENT" if after["inbox"] else "ABSENT"


def main():
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            report(STATUS="INPUT_REJECTED")
            return
        request = json.loads(raw)
        if (not isinstance(request, dict)
                or request.get("protocol") != "catalog-review-v1"
                or type(request.get("document_id")) is not int
                or request["document_id"] <= 0):
            report(STATUS="INPUT_REJECTED")
            return
        document_id = request["document_id"]

        from paperless.version import __full_version_str__
        from documents.models import Document

        if __full_version_str__ != "3.3.0":
            report(STATUS="VERSION_UNREVIEWED")
            return
        if JOURNAL.is_symlink() or JOURNAL.parent.is_symlink():
            report(STATUS="JOURNAL_UNSAFE")
            return
        if not JOURNAL.exists() or not stat.S_ISREG(JOURNAL.stat().st_mode):
            report(STATUS="JOURNAL_ABSENT")
            return

        # Existing sqlite database opened strictly read-only; no CREATE,
        # INSERT, UPDATE or maintenance. Do not trust or print its JSON.
        with sqlite3.connect(
            "file:" + str(JOURNAL) + "?mode=ro", uri=True, timeout=3
        ) as conn:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(
                "SELECT state,before_json,after_json FROM catalogue "
                "WHERE document_id=?", (document_id,)
            ).fetchall()
        if len(rows) != 1:
            report(STATUS="JOURNAL_ENTRY_ABSENT")
            return
        state, before_text, after_text = rows[0]
        if state not in STATES:
            report(STATUS="JOURNAL_STATE_UNVERIFIED")
            return
        doc = Document.objects.filter(pk=document_id).first()
        if doc is None:
            report(STATUS="DOCUMENT_ABSENT", JOURNAL_STATE=state)
            return

        before = json.loads(before_text)
        comparison, category, inbox = compare(
            before, live_snapshot(doc), document_id
        )
        after_recorded = bool(after_text)
        report(
            STATUS="INSPECTED", JOURNAL_STATE=state,
            SNAPSHOT_MATCH=comparison, DIFFERENCE_CATEGORY=category,
            INBOX_TAG=inbox,
            JOURNAL_AFTER_SNAPSHOT="PRESENT" if after_recorded else "ABSENT",
        )
    except Exception:
        # Never disclose filesystem paths, raw exception text,
        # document metadata or user identifiers.
        report(STATUS="UNVERIFIED")


# Call main() explicitly via the reviewed Ansible shell -c entrypoint.
