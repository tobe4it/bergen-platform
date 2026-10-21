"""Fail-closed, read-only Paperless 3.3 timer readiness for parents + notes + UI.

Reads only exact live configuration and model-level Note rights; never performs
inference, writes metadata, enables scheduling, creates a note or alters ACLs.
"""
import json
import sys

from django.contrib.auth.models import Group
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_AI_TIMER_READINESS_V1:"


def report(**fields):
    print(FRAME + json.dumps(fields, sort_keys=True), flush=True)


def main():
    try:
        req = json.load(sys.stdin)
        assert isinstance(req, dict) and set(req) == {
            "protocol", "model", "endpoint", "group",
        }
        assert req["protocol"] == "catalog-timer-ready-v1"
        assert __full_version_str__ == "3.3.0"
        assert ApplicationConfiguration.objects.count() == 1
        assert req["group"] == "Eltern@bergen.intern"
        group = Group.objects.get(name=req["group"])
        parents = list(group.user_set.filter(is_active=True))
        assert 1 <= len(parents) <= 6
        assert all(not p.is_staff and not p.is_superuser for p in parents)
        cfg = AIConfig()
        assert cfg.ai_enabled
        assert cfg.llm_backend == "ollama"
        assert cfg.llm_model == req["model"]
        assert cfg.llm_endpoint == req["endpoint"]
        assert cfg.llm_allow_internal_endpoints
        assert not cfg.llm_embedding_backend
        assert all(p.has_perm("documents.add_note")
                   and p.has_perm("documents.view_note")
                   for p in parents)
        report(AUDIT="READ_ONLY", STATUS="READY",
               PARENT_ACCOUNTS=len(parents),
               AI_UI_ENABLED="YES", EMBEDDINGS="OFF",
               NOTE_RIGHTS="READY", CHANGED=False)
    except Exception:
        report(AUDIT="FAILED_CLOSED", STATUS="NOT_READY", CHANGED=False)
        raise SystemExit(2)


main()
