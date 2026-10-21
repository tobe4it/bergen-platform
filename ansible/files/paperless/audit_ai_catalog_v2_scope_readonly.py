"""Strict read-only all-Posteingang import-date scope and journal audit.

No owner/group selection; no document IDs, content, titles or names printed.
No inference, writes, private metadata or retried documents.
"""
import json
from datetime import datetime
from pathlib import Path
import sqlite3
import stat
import sys
from zoneinfo import ZoneInfo

from documents.models import Document, Note
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_V2_SCOPE_AUDIT_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
CUTOFF = datetime(2026, 10, 1, tzinfo=ZoneInfo("Europe/Berlin"))
STATES = ("APPLIED", "NO_CHANGE", "PROCESSING", "REQUIRES_REVIEW", "ROLLED_BACK")
MAX_SCOPE = 5000


def emit(**values):
    print(FRAME + json.dumps(
        dict(AUDIT="READ_ONLY", CHANGED=False, MODEL_INFERENCE="NO",
             DOCUMENTS_CHANGED="NO", **values),
        sort_keys=True,
    ), flush=True)


def main():
    try:
        raw = sys.stdin.read(1025)
        request = json.loads(raw) if len(raw) <= 1024 else {}
        if (type(request) is not dict
                or request != {"protocol": "catalog-v2-scope-audit-v1"}
                or __full_version_str__ != "3.3.0"):
            return emit(STATUS="BLOCKED")
        queryset = Document.objects.filter(
            tags__is_inbox_tag=True, added__gte=CUTOFF
        ).distinct()
        total = queryset.count()
        if total > MAX_SCOPE:
            return emit(STATUS="BOUND_EXCEEDED")
        scope = list(queryset)
        ready_ids = set()
        all_ids = set()
        waiting_ocr_or_versions = 0
        for doc in scope:
            all_ids.add(doc.pk)
            if (len((doc.content or "").strip()) >= 30
                    and doc.root_document_id is None
                    and not doc.versions.exists()):
                ready_ids.add(doc.pk)
            else:
                waiting_ocr_or_versions += 1
        if (JOURNAL.parent.is_symlink() or JOURNAL.is_symlink()
                or not stat.S_ISREG(JOURNAL.stat().st_mode)):
            return emit(STATUS="BLOCKED")
        with sqlite3.connect(
            "file:" + str(JOURNAL) + "?mode=ro", uri=True, timeout=3
        ) as db:
            db.execute("PRAGMA query_only=ON")
            records = db.execute(
                "SELECT document_id, state FROM catalogue"
            ).fetchall()
        if len(records) > 100000:
            return emit(STATUS="BOUND_EXCEEDED")
        states = dict.fromkeys(STATES, 0)
        recorded = set()
        for doc_id, state in records:
            if doc_id in all_ids:
                if state not in states or doc_id in recorded:
                    return emit(STATUS="UNREVIEWED_JOURNAL_STATE")
                states[state] += 1
                recorded.add(doc_id)
        pending = len(ready_ids - recorded)
        waiting = len(all_ids - ready_ids)
        return emit(
            STATUS="INSPECTED",
            ALL_INBOX_ADDED_FROM_OCT1=total,
            OCR_READY_UNVERSIONED=len(ready_ids),
            WAITING_OCR_OR_VERSION_REVIEW=waiting,
            READY_UNJOURNALIZED=pending,
            SCOPE_JOURNAL_TOTAL=sum(states.values()),
            SCOPE_JOURNAL_STATES=states,
            SYSTEM_BAI_NOTES=Note.objects.filter(
                document_id__in=all_ids, user__isnull=True,
                note__startswith="Bergen-AI |",
            ).count(),
        )
    except Exception:
        return emit(STATUS="BLOCKED")


# Called only by the corresponding read-only Ansible playbook.
