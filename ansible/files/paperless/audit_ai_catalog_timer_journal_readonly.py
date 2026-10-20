"""Bergen Paperless 3.3.0: READ-ONLY timer watermark / private journal audit.

Invoked in the existing Paperless application via Django shell, with an exact
watermark read on the Proxmox host from the installed timer policy. Never
prints names, document IDs, OCR, notes, titles, owners, prompts, internal
addresses, policy values or error messages. No inference, locks, schema
changes, note creation, retries or permission modifications.
"""
import json
from pathlib import Path
import sqlite3
import stat
import sys

FRAME = "BERGEN_PAPERLESS_TIMER_JOURNAL_AUDIT_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
VALID_STATES = frozenset({
    "PROCESSING", "REQUIRES_REVIEW", "APPLIED", "NO_CHANGE", "ROLLED_BACK",
})


def emit(**fields):
    values = dict(
        AUDIT="READ_ONLY", CHANGED=False, MODEL_INFERENCE="NO",
        DOCUMENTS_CHANGED="NO", **fields,
    )
    print(FRAME + json.dumps(values, sort_keys=True), flush=True)


def validate(request):
    if not isinstance(request, dict) or set(request) != {
        "protocol", "watermark",
    }:
        return None
    if request["protocol"] != "timer-journal-readonly-v1":
        return None
    if type(request["watermark"]) is not int:
        return None
    if not 1 <= request["watermark"] < 2147483647:
        return None
    return request["watermark"]


def state_counts(rows):
    result = dict.fromkeys(sorted(VALID_STATES), 0)
    for state, count in rows:
        if (state not in VALID_STATES or type(count) is not int
                or count < 1):
            raise ValueError("UNREVIEWED_JOURNAL_STATE")
        result[state] += count
    return result


def journal_counts(watermark):
    # The service runs every five minutes and can write concurrently; use
    # SQLite's normal read transaction, not immutable=1 or a write lock.
    if JOURNAL.parent.is_symlink() or JOURNAL.is_symlink():
        raise ValueError("UNSAFE_JOURNAL_PATH")
    info = JOURNAL.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("JOURNAL_NOT_REGULAR")
    with sqlite3.connect("file:" + str(JOURNAL) + "?mode=ro",
                         uri=True, timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT state, COUNT(*) FROM catalogue "
            "WHERE document_id > ? GROUP BY state",
            (watermark,),
        ).fetchall()
    return state_counts(rows)


def main():
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            emit(STATUS="INPUT_REJECTED")
            return
        watermark = validate(json.loads(raw))
        if watermark is None:
            emit(STATUS="INPUT_REJECTED")
            return

        from paperless.version import __full_version_str__
        from django.contrib.auth.models import Group
        from django.db.models.functions import Length
        from documents.models import Document, Note
        if __full_version_str__ != "3.3.0":
            emit(STATUS="VERSION_UNREVIEWED")
            return
        group = Group.objects.get(name="Eltern@bergen.intern")
        counts = journal_counts(watermark)

        new_documents = Document.objects.filter(pk__gt=watermark).count()
        parent_inbox = Document.objects.filter(
            pk__gt=watermark,
            owner__is_active=True,
            owner__groups=group,
            tags__is_inbox_tag=True,
        ).distinct()
        new_parent_inbox = parent_inbox.count()
        ocr_ready = parent_inbox.annotate(
            text_len=Length("content")
        ).filter(text_len__gte=30).count()
        native_notes = Note.objects.filter(
            document__pk__gt=watermark,
            document__owner__groups=group,
            note__startswith="Bergen-AI |",
        ).count()
        emit(
            STATUS="INSPECTED",
            NEW_DOCUMENTS=new_documents,
            NEW_PARENT_INBOX_DOCUMENTS=new_parent_inbox,
            NEW_PARENT_INBOX_WITH_OCR=ocr_ready,
            NEW_PARENT_AI_NOTES=native_notes,
            POST_WATERMARK_JOURNAL_TOTAL=sum(counts.values()),
            POST_WATERMARK_STATES=counts,
        )
    except Exception:
        # No exception bodies or private metadata leave the protected guest.
        emit(STATUS="UNVERIFIED")


# The playbook appends main() to the in-container source.
