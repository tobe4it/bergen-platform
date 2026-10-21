"""Audit and separately enable Paperless 3.3 native notes for Bergen parents only.

No admin token, no document changes, no notes generated. Idempotent explicit
Django group model-permission grant, audited with bounded non-identifying output.
"""
import json
import sys

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import Note
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_NOTE_RIGHTS_V1:"


def report(**data):
    print(FRAME + json.dumps(data, sort_keys=True), flush=True)


def run():
    try:
        req = json.load(sys.stdin)
        assert isinstance(req, dict) and set(req) == {
            "protocol", "mode", "approved", "backup_verified", "group",
        }
        assert req["protocol"] == "notes-permissions-v1"
        assert req["mode"] in ("audit", "apply")
        assert type(req["approved"]) is bool
        assert type(req["backup_verified"]) is bool
        assert __full_version_str__ == "3.3.0"
        assert req["group"] == "Eltern@bergen.intern"
        group = Group.objects.get(name=req["group"])
        members = list(group.user_set.filter(is_active=True))
        assert 1 <= len(members) <= 6
        assert all(not user.is_staff and not user.is_superuser for user in members)
        assert not group.user_set.exclude(is_active=True).exists()
        content_type = ContentType.objects.get_for_model(Note)
        rights = list(Permission.objects.filter(
            content_type=content_type, codename__in=("add_note", "view_note"),
        ))
        assert {p.codename for p in rights} == {"add_note", "view_note"}
        assert all(p.content_type.app_label == "documents" for p in rights)
        missing = sum(not member.has_perm("documents.add_note")
                      or not member.has_perm("documents.view_note")
                      for member in members)
        if req["mode"] == "audit":
            report(AUDIT="READ_ONLY", STATUS="INSPECTED",
                   ADULT_ACCOUNTS=len(members), MISSING_NOTE_RIGHTS=missing,
                   CHANGED=False)
            return
        assert req["approved"] and req["backup_verified"]
        with transaction.atomic():
            locked = Group.objects.select_for_update().get(pk=group.pk)
            assert locked.name == "Eltern@bergen.intern"
            changed = [p for p in rights if not locked.permissions.filter(pk=p.pk).exists()]
            if changed:
                locked.permissions.add(*changed)
            assert all(locked.permissions.filter(pk=p.pk).exists() for p in rights)
        report(AUDIT="CONTROLLED", STATUS="NOTE_RIGHTS_READY",
               ADULT_ACCOUNTS=len(members), MODEL_RIGHTS_ADDED=len(changed),
               CHANGED=bool(changed))
    except Exception:
        report(AUDIT="FAILED_CLOSED", STATUS="NOTES_RIGHTS_UNVERIFIED",
               CHANGED=False)
        raise SystemExit(2)


run()
