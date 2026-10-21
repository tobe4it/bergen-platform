"""Read-only preparation for full Inbox Oct-2026 replay (all owners, including null).

No model call, updates, locks, notes or IDs/titles/text in the output.
Reads installed private journal only in SQLite mode=ro.
"""
import json
from datetime import datetime
from pathlib import Path
import sqlite3
import stat

from documents.models import Document
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_ALL_INBOX_OCT_AUDIT_V1:"
CUTOFF = datetime.fromisoformat("2026-10-01T00:00:00+02:00")
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
STATES = ("APPLIED", "NO_CHANGE", "PROCESSING", "REQUIRES_REVIEW", "ROLLED_BACK")


def print_frame(**data):
    print(FRAME + json.dumps(dict(AUDIT="READ_ONLY", CHANGED=False,
        MODEL_INFERENCE="NO", DOCUMENTS_CHANGED="NO", **data),
        sort_keys=True), flush=True)


def entries():
    if JOURNAL.parent.is_symlink() or JOURNAL.is_symlink():
        raise ValueError("UNSAFE_JOURNAL")
    if not stat.S_ISREG(JOURNAL.stat().st_mode):
        raise ValueError("INVALID_JOURNAL")
    with sqlite3.connect("file:" + str(JOURNAL) + "?mode=ro",
                         uri=True, timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT document_id, state FROM catalogue").fetchall()
    if len(rows) > 100000:
        raise ValueError("UNBOUNDED_JOURNAL")
    states = {}
    for doc_id, state in rows:
        if type(doc_id) is not int or doc_id <= 0 or state not in STATES:
            raise ValueError("INVALID_JOURNAL_STATE")
        if doc_id in states:
            raise ValueError("DUPLICATE_JOURNAL")
        states[doc_id] = state
    return states


def main():
    try:
        if __full_version_str__ != "3.3.0":
            print_frame(STATUS="VERSION_UNREVIEWED")
            return
        states = entries()
        base = Document.objects.filter(
            added__gte=CUTOFF, tags__is_inbox_tag=True,
        ).distinct().select_related("owner")
        total = base.count()
        if total > 100000:
            print_frame(STATUS="SCOPE_TOO_LARGE")
            return
        eligible = 0
        ownerless = 0
        no_ocr_or_versions = 0
        previously_recorded = 0
        pending = 0
        state_counts = {key: 0 for key in STATES}
        for doc in base.iterator(chunk_size=100):
            if doc.owner_id is None:
                ownerless += 1
            if not doc.content or len(doc.content.strip()) < 30:
                no_ocr_or_versions += 1
                continue
            if doc.root_document_id is not None or doc.versions.exists():
                no_ocr_or_versions += 1
                continue
            eligible += 1
            if doc.pk in states:
                previously_recorded += 1
                state_counts[states[doc.pk]] += 1
            else:
                pending += 1
        print_frame(
            STATUS="INSPECTED",
            IMPORT_CUTOFF="2026-10-01",
            ALL_INBOX_IMPORTED_FROM_CUTOFF=total,
            OWNERLESS_INBOX=ownerless,
            READY_FOR_CLASSIFICATION=eligible,
            WAITING_FOR_OCR_OR_UNSUPPORTED_VERSION=no_ocr_or_versions,
            ALREADY_JOURNALED=previously_recorded,
            PENDING_NOT_JOURNALED=pending,
            EXISTING_JOURNAL_STATES=state_counts,
        )
    except Exception:
        print_frame(STATUS="UNVERIFIED")


main()
