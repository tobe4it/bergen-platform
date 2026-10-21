"""Version-pinned, idempotent configuration of Paperless native AI suggestion UI.

Global Paperless AI master switch only; no embedding backend, index, document
modification, note creation, workflow trigger, credential change, or remote AI.
Requires explicit site approval and the 19 October backup acceptance (or newer).
"""
import hashlib
import json
import sys
from django.db import transaction
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_NATIVE_AI_UI_V1:"


def report(**values):
    print(FRAME + json.dumps(values, sort_keys=True), flush=True)


def digest(fields):
    return hashlib.sha256(json.dumps(
        fields, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def state(obj):
    return {
        "ai_enabled": obj.ai_enabled,
        "llm_backend": obj.llm_backend,
        "llm_model": obj.llm_model,
        "llm_endpoint": obj.llm_endpoint,
        "llm_embedding_backend": obj.llm_embedding_backend,
    }


def run():
    try:
        req = json.load(sys.stdin)
        if not isinstance(req, dict) or set(req) != {
            "protocol", "mode", "approved", "backup_verified",
            "expected_model", "expected_endpoint", "expected_sha256",
        }:
            report(AUDIT="FAILED_CLOSED", CODE="INPUT_INVALID", CHANGED=False)
            raise SystemExit(2)
        if (req["protocol"] != "native-ai-ui-v1"
                or req["mode"] not in ("audit", "apply")
                or type(req["approved"]) is not bool
                or type(req["backup_verified"]) is not bool
                or __full_version_str__ != "3.3.0"
                or ApplicationConfiguration.objects.count() != 1):
            report(AUDIT="FAILED_CLOSED", CODE="SCOPE_UNVERIFIED", CHANGED=False)
            raise SystemExit(2)

        cfg = AIConfig()
        obj = ApplicationConfiguration.objects.get()
        current = state(obj)
        expected_hash = digest(current)
        if (cfg.llm_backend != "ollama"
                or cfg.llm_model != req["expected_model"]
                or cfg.llm_endpoint != req["expected_endpoint"]
                or not cfg.llm_allow_internal_endpoints
                or cfg.llm_embedding_backend
                or current["llm_embedding_backend"]):
            report(AUDIT="FAILED_CLOSED", CODE="LOCAL_AI_POLICY_INVALID", CHANGED=False)
            raise SystemExit(2)

        if req["mode"] == "audit":
            report(AUDIT="READ_ONLY", STATUS="INSPECTED",
                   AI_UI_ENABLED=bool(cfg.ai_enabled),
                   EMBEDDINGS="OFF", CURRENT_SHA256=expected_hash,
                   CHANGED=False)
            return
        if not req["approved"] or not req["backup_verified"]:
            report(AUDIT="FAILED_CLOSED", CODE="APPROVAL_REQUIRED", CHANGED=False)
            raise SystemExit(2)
        if req["expected_sha256"] != expected_hash or len(expected_hash) != 64:
            report(AUDIT="FAILED_CLOSED", CODE="FINGERPRINT_CHANGED", CHANGED=False)
            raise SystemExit(2)

        with transaction.atomic():
            obj = ApplicationConfiguration.objects.select_for_update().get(pk=obj.pk)
            if digest(state(obj)) != expected_hash:
                report(AUDIT="FAILED_CLOSED", CODE="FINGERPRINT_CHANGED", CHANGED=False)
                raise SystemExit(2)
            changed = not obj.ai_enabled
            if changed:
                obj.ai_enabled = True
                obj.save(update_fields=["ai_enabled"])

        report(AUDIT="CONTROLLED", STATUS="NATIVE_AI_UI_ENABLED",
               AI_UI_ENABLED=True, EMBEDDINGS="OFF", CHANGED=changed)
    except SystemExit:
        raise
    except Exception:
        report(AUDIT="FAILED_CLOSED", CODE="UNVERIFIED_RUNTIME", CHANGED=False)
        raise SystemExit(2)


run()
