"""Version-pinned Paperless-ngx native German AI + local document chat.

Django manage.py shell script. Audit is strictly read-only, apply changes
ONLY four ApplicationConfiguration fields after exact fingerprint, version,
backend, model, private endpoint and separate backup/approval gates.
No document/ACL/index modification, credentials or document text output.
Index rebuild is a SEPARATE authorized operation after enabling chat.
"""
import hashlib
import ipaddress
import json
import socket
import sys
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

from django.conf import settings
from django.db import transaction
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_NATIVE_DE_CHAT_V1:"
NEW_FIELDS = {
    "ai_enabled": True,
    "llm_output_language": "de",
    "llm_embedding_backend": "ollama",
    "llm_embedding_model": "bge-m3:latest",
}
FIELDS = (
    "ai_enabled", "llm_output_language", "llm_embedding_backend",
    "llm_embedding_model", "llm_backend", "llm_model", "llm_endpoint",
    "llm_embedding_endpoint", "llm_embedding_api_key",
)
MAX_INPUT = 2048


def emit(**result):
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def private_endpoint(url):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.port != 11434 or not parsed.hostname):
        return False
    try:
        addrs = socket.getaddrinfo(parsed.hostname, 11434, type=socket.SOCK_STREAM)
        return bool(addrs) and all(
            ipaddress.ip_address(a[4][0]).is_private
            and not ipaddress.ip_address(a[4][0]).is_link_local
            and not ipaddress.ip_address(a[4][0]).is_unspecified
            for a in addrs
        )
    except (OSError, ValueError):
        return False


def local_model_tags(endpoint):
    if not private_endpoint(endpoint):
        return set()
    try:
        req = Request(endpoint.rstrip("/") + "/api/tags",
                      headers={"Accept": "application/json"}, method="GET")
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=5) as response:
            if response.status != 200:
                return set()
            raw = response.read(256001)
        if len(raw) > 256000:
            return set()
        models = json.loads(raw).get("models", [])
        if not isinstance(models, list) or len(models) > 300:
            return set()
        return {m.get("name") for m in models if isinstance(m, dict)
                and isinstance(m.get("name"), str)}
    except (OSError, ValueError, TypeError):
        return set()


def snapshot(instance):
    return {key: getattr(instance, key) for key in FIELDS}


def fingerprint(data):
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def main():
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            return emit(STATUS="BLOCKED", CODE="INPUT_INVALID", CHANGED=False)
        request = json.loads(raw)
        if (type(request) is not dict or
                request.get("protocol") != "native-de-chat-v1" or
                request.get("mode") not in ("audit", "apply") or
                __full_version_str__ != "3.3.0" or
                ApplicationConfiguration.objects.count() != 1):
            return emit(STATUS="BLOCKED", CODE="CONFIG_UNREVIEWED", CHANGED=False)
        obj = ApplicationConfiguration.objects.first()
        before = snapshot(obj)
        digest = fingerprint(before)
        effective = AIConfig()
        tags = local_model_tags(effective.llm_endpoint)
        base_ok = (
            effective.llm_backend == "ollama"
            and private_endpoint(effective.llm_endpoint)
            and effective.llm_allow_internal_endpoints
            and effective.llm_model in tags
            and effective.llm_model == request.get("expected_model")
            and effective.llm_endpoint == request.get("expected_endpoint")
        )
        embedding_ok = "bge-m3:latest" in tags
        current_index = effective.llm_embedding_backend
        index_reviewed = current_index in (None, "", "ollama")
        model_reviewed = effective.llm_embedding_model in (
            None, "", "embeddinggemma", "bge-m3", "bge-m3:latest"
        )
        effective_language = effective.llm_output_language
        ready = (base_ok and embedding_ok and index_reviewed and model_reviewed)
        if request["mode"] == "audit":
            return emit(
                AUDIT="READ_ONLY", STATUS="INSPECTED",
                AI_UI="YES" if effective.ai_enabled else "NO",
                OUTPUT_LANGUAGE="DE" if effective_language == "de" else
                    ("UNSET" if not effective_language else "OTHER"),
                INDEX="OFF" if not current_index else (
                    "LOCAL_OLLAMA" if current_index == "ollama" else "OTHER"),
                GENERATION_MODEL="REVIEWED" if base_ok else "NOT_REVIEWED",
                EMBEDDING_MODEL="BGE_M3_LOCAL" if embedding_ok else "NOT_READY",
                NEW_INDEX_COMPATIBLE="YES" if index_reviewed and model_reviewed else "NO",
                CURRENT_SHA256=digest, CHANGED=False,
                INDEX_CHANGED=False, DOCUMENTS_CHANGED=False,
            )
        if (request.get("approved") is not True
                or request.get("backup_verified") is not True
                or request.get("chat_index_permission_reviewed") is not True
                or not isinstance(request.get("expected_sha256"), str)
                or request["expected_sha256"] != digest):
            return emit(STATUS="BLOCKED", CODE="APPROVAL_OR_FINGERPRINT", CHANGED=False)
        if not ready:
            return emit(STATUS="BLOCKED", CODE="LOCAL_MODEL_OR_INDEX_NOT_READY",
                        CHANGED=False)
        # Application config settings stored in DB override environment.
        # Refuse an existing index pointing to a different backend/model.
        if current_index == "ollama" and effective.llm_embedding_model not in (
            "bge-m3", "bge-m3:latest",
        ):
            return emit(STATUS="BLOCKED", CODE="INDEX_MODEL_CONFLICT", CHANGED=False)
        if (before["llm_embedding_api_key"] or
                before["llm_embedding_endpoint"] not in (None, "", effective.llm_endpoint)):
            return emit(STATUS="BLOCKED", CODE="EXTERNAL_EMBEDDING_CONFIG",
                        CHANGED=False)
        if all(before[k] == v for k, v in NEW_FIELDS.items()):
            return emit(AUDIT="CONTROLLED", STATUS="ALREADY_CONFIGURED",
                        CHANGED=False, INDEX_CHANGED=False, DOCUMENTS_CHANGED=False)
        with transaction.atomic():
            locked = ApplicationConfiguration.objects.select_for_update().get(pk=obj.pk)
            if fingerprint(snapshot(locked)) != digest:
                return emit(STATUS="BLOCKED", CODE="CONFIG_CHANGED", CHANGED=False)
            for key, value in NEW_FIELDS.items():
                setattr(locked, key, value)
            locked.save(update_fields=list(NEW_FIELDS))
        checked = AIConfig()
        if not (checked.ai_enabled and checked.llm_output_language == "de"
                and checked.llm_embedding_backend == "ollama"
                and checked.llm_embedding_model == "bge-m3:latest"
                and checked.llm_backend == "ollama"):
            return emit(STATUS="BLOCKED", CODE="AFTER_WRITE_NOT_VERIFIED",
                        CHANGED=True)
        emit(AUDIT="CONTROLLED", STATUS="GERMAN_NATIVE_AI_CHAT_CONFIGURED",
             CHANGED=True, INDEX_CHANGED=False, DOCUMENTS_CHANGED=False)
    except Exception:
        emit(STATUS="BLOCKED", CODE="UNCLASSIFIED", CHANGED=False)


main()
