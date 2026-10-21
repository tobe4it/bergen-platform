"""Bounded read-only Bergen-AI v2 scope summary (no document identifiers).

Shows the exact import-date selection, ownerless Eltern group visibility,
OCR-ready candidates, already journalized scope, notes and terminal states.
No model call, locks or writes; no credentials, text or metadata logged.
"""
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.db.models.functions import Cast
from django.db.models import IntegerField
from guardian.models import GroupObjectPermission
from documents.models import Document, Note
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_V2_SCOPE_AUDIT_V1:"
DB = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
CUTOFF = datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
STATES = ("APPLIED", "NO_CHANGE", "PROCESSING", "REQUIRES_REVIEW", "ROLLED_BACK")
MAX_SCOPE = 5000


def emit(**values):
    payload = dict(
        AUDIT="READ_ONLY", CHANGED=False, MODEL_INFERENCE="NO",
        DOCUMENTS_CHANGED="NO", **values,
    )
    print(FRAME + json.dumps(payload, sort_keys=True), flush=True)


def main():
    try:
        raw = sys.stdin.read(1025)
        request = json.loads(raw) if len(raw) <= 1024 else {}
        if (type(request) is not dict
                or request != {"protocol": "catalog-v2-scope-audit-v1"}
                or __full_version_str__ != "3.3.0"):
            return emit(STATUS="BLOCKED")
        docs = Document.objects.filter(
            tags__is_inbox_tag=True, added__gte=CUTOFF
        ).distinct().order_by("pk")
        total = docs.count()
        if total > MAX_SCOPE:
            return emit(STATUS="BOUND_EXCEEDED")
        rows = list(docs.select_related("owner"))
        group = Group.objects.get(name="Eltern@bergen.intern")
        ct = ContentType.objects.get_for_model(Document)
        parent_ids = set(
            GroupObjectPermission.objects.filter(
                content_type=ct, permission__content_type=ct,
                permission__codename__in=("view_document", "change_document"),
                group=group,
            ).annotate(object_pk_int=Cast("object_pk", IntegerField()))
             .values_list("object_pk_int", flat=True)
        )
        ownerless_parent = 0
        ready = 0
        ownerless_parent_ready = 0
        id_set = set()
        for d in rows:
            has_ocr = len((d.content or "").strip()) >= 30
            ready_doc = (
                has_ocr and d.root_document_id is None
                and not d.versions.exists()
            )
            if ready_doc:
                ready += 1
            if d.owner_id is None and d.pk in parent_ids:
                ownerless_parent += 1
                if ready_doc:
                    ownerless_parent_ready += 1
            id_set.add(d.pk)
        if DB.is_symlink() or DB.parent.is_symlink():
            return emit(STATUS="BLOCKED")
        with sqlite3.connect(
            "file:" + str(DB) + "?mode=ro", uri=True, timeout=3
        ) as conn:
            conn.execute("PRAGMA query_only=ON")
            records = conn.execute(
                "SELECT document_id, state FROM catalogue",
            ).fetchall()
        states = dict.fromkeys(STATES, 0)
        parent_pending = 0
        in_scope_journal = set()
        for doc_id, state in records:
            if doc_id in id_set:
                if state not in states:
                    return emit(STATUS="UNREVIEWED_JOURNAL_STATE")
                states[state] += 1
                in_scope_journal.add(doc_id)
        for d in rows:
            if (d.owner_id is None and d.pk in parent_ids
                    and d.pk not in in_scope_journal
                    and len((d.content or "").strip()) >= 30
                    and d.root_document_id is None and not d.versions.exists()):
                parent_pending += 1
        notes = Note.objects.filter(
            document__pk__in=id_set, user__isnull=True,
            note__startswith="Bergen-AI |",
        ).count()
        return emit(
            STATUS="INSPECTED",
            TOTAL_POSTEINGANG_ADDED_SINCE_OCT1=total,
            OCR_READY_UNVERSIONED=ready,
            OWNERLESS_PARENT_SHARED=ownerless_parent,
            OWNERLESS_PARENT_READY=ownerless_parent_ready,
            OWNERLESS_PARENT_UNJOURNALIZED_READY=parent_pending,
            IN_SCOPE_JOURNAL_TOTAL=sum(states.values()),
            IN_SCOPE_JOURNAL_STATES=states,
            SYSTEM_BAI_NOTES=notes,
        )
    except Exception:
        return emit(STATUS="BLOCKED")


# Explicitly appended by the Ansible read-only playbook.
