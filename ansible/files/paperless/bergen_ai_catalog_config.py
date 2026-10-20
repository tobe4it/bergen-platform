"""Issue #113: configure only local Ollama backend/model/endpoint in v3.3.0.

This NEVER turns on Paperless's global AI UI or vector index. The controlled
catalogue worker may call the native classifier directly with AI master OFF.
Default mode: read-only audit; apply and rollback require a separate verified
backup, explicit approval and an exact optimistic config fingerprint.
Input via Ansible stdin; output only bounded counts/status/fingerprints.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

from django.conf import settings
from django.db import transaction
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_AI_LOCAL_CONFIG_V1:"
BASE = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1")
BACKUP = BASE / "original-ai-config.json"


def status(**kwargs):
    print(FRAME + json.dumps(kwargs, sort_keys=True), flush=True)


def raw_state(obj):
    return {
        "ai_enabled": obj.ai_enabled,
        "llm_backend": obj.llm_backend,
        "llm_model": obj.llm_model,
        "llm_endpoint": obj.llm_endpoint,
        "llm_embedding_backend": obj.llm_embedding_backend,
    }


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_envelope(req):
    demand(__full_version_str__ == "3.3.0", "VERSION_UNREVIEWED")
    demand(isinstance(req, dict) and req.get("protocol") == "catalog-config-v1",
           "INPUT_INVALID")
    demand(req.get("mode") in ("audit", "apply", "rollback"), "MODE_INVALID")
    demand(ApplicationConfiguration.objects.count() == 1, "APP_CONFIG_UNREVIEWED")
    effective = AIConfig()
    # Local backend configuration may be audited even after a separately
    # approved native AI UI enablement; embeddings must always stay OFF.
    demand(not effective.llm_embedding_backend,
           "GLOBAL_AI_OR_INDEX_ALREADY_ACTIVE")
    demand(req.get("mode") == "audit" or not effective.ai_enabled,
           "GLOBAL_AI_OR_INDEX_ALREADY_ACTIVE")
    demand(not settings.AI_ENABLED and not settings.LLM_EMBEDDING_BACKEND,
           "GLOBAL_AI_OR_INDEX_ENV_CONFLICT")
    demand(settings.LLM_ALLOW_INTERNAL_ENDPOINTS, "LOCAL_OLLAMA_NOT_PERMITTED")
    if effective.llm_backend not in (None, "", "ollama"):
        demand(req.get("mode") == "audit", "EXTERNAL_PROVIDER_REVIEW_REQUIRED")
    return effective


def main():
    try:
        req = json.load(sys.stdin)
        verify_envelope(req)
        obj = ApplicationConfiguration.objects.first()
        current = raw_state(obj)
        fingerprint = sha(current)
        mode = req["mode"]
        if mode == "audit":
            status(AUDIT="READ_ONLY", STATUS="INSPECTED",
                   AI_UI_ENABLED="YES" if effective.ai_enabled else "NO", EMBEDDINGS="OFF",
                   CURRENT_SHA256=fingerprint, CHANGED=False)
            return
        demand(req.get("approved") is True, "APPROVAL_REQUIRED")
        demand(req.get("backup_verified") is True, "BACKUP_NOT_VERIFIED")
        demand(req.get("expected_sha256") == fingerprint, "FINGERPRINT_CHANGED")
        demand(not obj.ai_enabled and not obj.llm_embedding_backend,
               "GLOBAL_AI_OR_INDEX_ALREADY_ACTIVE")
        if mode == "rollback":
            demand(BACKUP.is_file() and not BACKUP.is_symlink(),
                   "ROLLBACK_BACKUP_MISSING")
            snapshot = json.loads(BACKUP.read_text())
            demand(set(snapshot) == set(current), "ROLLBACK_UNREVIEWED")
            original = snapshot
            # Rollback is allowed only with explicit approval, and will
            # re-check the same config fingerprint under database row lock.
            target = {
                "llm_backend": original["llm_backend"],
                "llm_model": original["llm_model"],
                "llm_endpoint": original["llm_endpoint"],
            }
        else:
            endpoint, model = req.get("endpoint"), req.get("model")
            demand(safe_endpoint(endpoint), "ENDPOINT_INVALID")
            demand(isinstance(model, str) and 1 <= len(model) <= 96
                   and all(c.isalnum() or c in ".:_-" for c in model),
                   "MODEL_INVALID")
            target = {
                "llm_backend": "ollama",
                "llm_model": model,
                "llm_endpoint": endpoint,
            }
            demand(obj.llm_backend in (None, "", "ollama"),
                   "EXTERNAL_PROVIDER_REVIEW_REQUIRED")
            # Never overwrite another prior preimage; require rollback
            # and a new review rather than silently replacing the backup.
            demand(not BACKUP.exists() and not BACKUP.is_symlink(),
                   "PRIOR_BACKUP_REQUIRES_REVIEW")
            demand(BASE.parent.is_dir() and not BASE.parent.is_symlink(),
                   "DATA_MOUNT_INVALID")
            demand(not BASE.is_symlink(), "DATA_MOUNT_INVALID")
            BASE.mkdir(mode=0o700, exist_ok=True)
            os.chmod(BASE, 0o700)
            previous = json.dumps(current, sort_keys=True)
            fd = os.open(str(BACKUP), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(previous)
                handle.flush()
                os.fsync(handle.fileno())
        with transaction.atomic():
            locked = ApplicationConfiguration.objects.select_for_update().get(pk=obj.pk)
            demand(sha(raw_state(locked)) == fingerprint,
                   "FINGERPRINT_CHANGED")
            for field, value in target.items():
                setattr(locked, field, value)
            locked.save(update_fields=list(target))
        status(AUDIT="CONTROLLED", STATUS="CONFIG_ROLLED_BACK" if mode == "rollback"
               else "LOCAL_LLM_CONFIG_APPLIED",
               AI_UI_ENABLED="NO", EMBEDDINGS="OFF", CHANGED=True)
    except PolicyError as exc:
        allowed = {
            "VERSION_UNREVIEWED", "INPUT_INVALID", "MODE_INVALID",
            "APP_CONFIG_UNREVIEWED", "GLOBAL_AI_OR_INDEX_ALREADY_ACTIVE",
            "GLOBAL_AI_OR_INDEX_ENV_CONFLICT", "LOCAL_OLLAMA_NOT_PERMITTED",
            "EXTERNAL_PROVIDER_REVIEW_REQUIRED", "APPROVAL_REQUIRED",
            "BACKUP_NOT_VERIFIED", "FINGERPRINT_CHANGED",
            "ROLLBACK_BACKUP_MISSING", "ROLLBACK_UNREVIEWED",
            "ENDPOINT_INVALID", "MODEL_INVALID",
            "PRIOR_BACKUP_REQUIRES_REVIEW", "DATA_MOUNT_INVALID",
        }
        status(AUDIT="FAILED_CLOSED",
               CODE=str(exc) if str(exc) in allowed else "POLICY_REJECTED",
               CHANGED=False)
        raise SystemExit(2)
    except Exception:
        status(AUDIT="FAILED_CLOSED", CODE="UNCLASSIFIED_FAILURE",
               CHANGED=False)
        raise SystemExit(2)


main()
