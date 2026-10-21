"""Paperless v2: immutable eligibility attestation for one shared Eltern document.

Executed within Django shell by controlled Ansible playbook. No document
content, IDs, taxonomy, group membership, notes or host details printed.
Never creates a journal file or invokes inference.
"""
import json
from pathlib import Path
import sqlite3
import stat
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from guardian.models import GroupObjectPermission
from documents.models import Document
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_V2_OWNERLESS_PILOT_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
CUTOFF = datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))


def emit(status):
    print(FRAME + json.dumps({
        "AUDIT": "READ_ONLY", "STATUS": status,
        "CHANGED": False, "MODEL_INFERENCE": "NO",
    }, sort_keys=True), flush=True)


def main():
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            return emit("BLOCKED")
        req = json.loads(raw)
        if (type(req) is not dict or set(req) != {"protocol", "document_id"}
                or req["protocol"] != "catalog-v2-ownerless-pilot-check-v1"
                or type(req["document_id"]) is not int
                or not 1 <= req["document_id"] <= 999999999
                or __full_version_str__ != "3.3.0"):
            return emit("BLOCKED")
        d = Document.objects.filter(pk=req["document_id"]).first()
        if (d is None or d.owner_id is not None or d.added is None
                or d.added < CUTOFF
                or not d.tags.filter(is_inbox_tag=True).exists()
                or len((d.content or "").strip()) < 30
                or d.root_document_id is not None or d.versions.exists()):
            return emit("BLOCKED")
        group = Group.objects.get(name="Eltern@bergen.intern")
        ct = ContentType.objects.get_for_model(Document)
        if not GroupObjectPermission.objects.filter(
            group=group, content_type=ct,
            permission__content_type=ct,
            permission__codename__in=("view_document", "change_document"),
            object_pk=str(d.pk),
        ).exists():
            return emit("BLOCKED")
        if JOURNAL.parent.is_symlink() or JOURNAL.is_symlink():
            return emit("BLOCKED")
        statinfo = JOURNAL.stat()
        if not stat.S_ISREG(statinfo.st_mode):
            return emit("BLOCKED")
        with sqlite3.connect(
            "file:" + str(JOURNAL) + "?mode=ro", uri=True, timeout=3
        ) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute(
                "SELECT 1 FROM catalogue WHERE document_id=?",
                (d.pk,),
            ).fetchone():
                return emit("ALREADY_RECORDED")
        return emit("READY")
    except Exception:
        return emit("BLOCKED")


# The Ansible caller appends main() once at execution time.
