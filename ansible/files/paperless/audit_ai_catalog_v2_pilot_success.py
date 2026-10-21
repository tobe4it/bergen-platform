"""Read-only v2 pilot proof for an ownerless Eltern-group document.

Checks SQLite journal successful terminal state, system-authored native Note,
existing Inbox, import date, and unchanged owner/group-sharing envelope.
Does not reclassify or retry any document.
"""
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from guardian.models import GroupObjectPermission
from documents.models import Document, Note
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_V2_PILOT_PROOF_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
CUTOFF = datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))


def emit(status):
    print(FRAME + json.dumps(
        {"AUDIT": "READ_ONLY", "STATUS": status, "CHANGED": False},
        sort_keys=True,
    ), flush=True)


def main():
    try:
        raw = sys.stdin.read(1025)
        req = json.loads(raw) if len(raw) <= 1024 else {}
        if (type(req) is not dict or set(req) != {"protocol", "document_id"}
                or req.get("protocol") != "catalog-v2-pilot-proof-v1"
                or type(req.get("document_id")) is not int
                or not 1 <= req["document_id"] <= 999999999
                or __full_version_str__ != "3.3.0"):
            return emit("BLOCKED")
        doc = Document.objects.filter(pk=req["document_id"]).first()
        if (doc is None or doc.owner_id is not None
                or doc.added is None or doc.added < CUTOFF
                or not doc.tags.filter(is_inbox_tag=True).exists()):
            return emit("BLOCKED")
        group = Group.objects.get(name="Eltern@bergen.intern")
        ct = ContentType.objects.get_for_model(Document)
        if not GroupObjectPermission.objects.filter(
            group=group, content_type=ct,
            permission__content_type=ct,
            permission__codename__in=("view_document", "change_document"),
            object_pk=str(doc.pk),
        ).exists():
            return emit("BLOCKED")
        if JOURNAL.is_symlink() or JOURNAL.parent.is_symlink():
            return emit("BLOCKED")
        with sqlite3.connect(
            "file:" + str(JOURNAL) + "?mode=ro", uri=True, timeout=3
        ) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT state,after_json,applied_json FROM catalogue "
                "WHERE document_id=?", (doc.pk,),
            ).fetchone()
        if not row or row[0] not in ("APPLIED", "NO_CHANGE"):
            return emit("BLOCKED")
        after = json.loads(row[1]) if row[1] else {}
        changes = json.loads(row[2]) if row[2] else {}
        if (after.get("owner_id") is not None
                or not after.get("inbox")
                or changes.get("review_note_created") is not True):
            return emit("BLOCKED")
        if not Note.objects.filter(
            document=doc, user__isnull=True,
            note__startswith="Bergen-AI |",
        ).exists():
            return emit("BLOCKED")
        return emit("PASSED")
    except Exception:
        return emit("BLOCKED")


# Appended by the Ansible playbook: main()
