"""Issue #113 – Paperless-ngx 3.3.0 local AI inbox cataloguer.

Invoked inside the running Django application by 'manage.py shell -c'.
The pure bergen_ai_catalog_policy.py module is concatenated before this
code by Ansible (no new Paperless package or API tokens are installed).
Only status classifications are printed; NEVER log OCR text, metadata, IDs
or AI prompts. The container's EXISTING persistent data mount holds a
0600 crash-safe processing journal and 0700 lock directory.

Pilot and automatic modes are distinct: apply requires explicit approval;
automatic mode requires a positive post-activation watermark. User-checked
documents (no inbox tag) are never changed, even after a failed run.
"""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from django.contrib.auth.models import Group
from django.db import transaction
from documents.models import Correspondent, Document, DocumentType, Tag
from documents.workflows.ai import resolve_object, resolve_tags
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__
from paperless_ai.ai_classifier import get_ai_document_classification
from paperless_ai.matching import (
    match_correspondents_by_name, match_document_types_by_name,
    match_tags_by_name, resolve_correspondent_ids,
    resolve_document_type_ids, resolve_tag_ids,
)

FRAME = "BERGEN_PAPERLESS_AI_CATALOG_V1:"
JOURNAL_BASE = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1")
JOURNAL_DB = JOURNAL_BASE / "catalog.sqlite3"
MAX_BATCH = 2


def report(**kwargs):
    print(FRAME + json.dumps(kwargs, sort_keys=True), flush=True)


def snapshot(doc):
    return {
        "id": doc.pk, "owner_id": doc.owner_id, "title": doc.title,
        "original_filename": doc.original_filename or "",
        "correspondent_id": doc.correspondent_id,
        "document_type_id": doc.document_type_id,
        "storage_path_id": doc.storage_path_id,
        "created": doc.created.isoformat(),
        "modified": doc.modified.isoformat(),
        "checksum": doc.checksum,
        "content_sha256": __import__("hashlib").sha256(
            (doc.content or "").encode()).hexdigest(),
        "tag_ids": sorted(doc.tags.values_list("id", flat=True)),
        "inbox": doc.tags.filter(is_inbox_tag=True).exists(),
    }


def dns_is_private(endpoint):
    host = urlsplit(endpoint).hostname
    if not host:
        return False
    try:
        addresses = socket.getaddrinfo(host, 11434, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(a[4][0]).is_private
            and not ipaddress.ip_address(a[4][0]).is_link_local
            and not ipaddress.ip_address(a[4][0]).is_unspecified
            for a in addresses
        )
    except (OSError, ValueError):
        return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ollama_model_available(endpoint, expected_model):
    """Read Ollama's local model list only, never follow redirects or a proxy."""
    if not safe_endpoint(endpoint) or not dns_is_private(endpoint):
        return False
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        req = Request(endpoint.rstrip("/") + "/api/tags",
                      headers={"Accept": "application/json"}, method="GET")
        with opener.open(req, timeout=5) as resp:
            if resp.status != 200:
                return False
            payload = resp.read(256001)
        if len(payload) > 256000:
            return False
        models = json.loads(payload).get("models", [])
        if not isinstance(models, list) or len(models) > 300:
            return False
        return any(isinstance(m, dict) and m.get("name") == expected_model
                   for m in models)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def ensure_config(request, *, apply):
    demand(__full_version_str__ == "3.3.0", "PAPERLESS_VERSION_UNREVIEWED")
    demand(isinstance(request, dict)
           and request.get("protocol") == "catalog-v1", "INPUT_INVALID")
    demand(request.get("mode") in ("audit", "preview", "apply", "rollback"),
           "MODE_INVALID")
    group_name = request.get("allowed_group")
    demand(isinstance(group_name, str) and 1 <= len(group_name) <= 150
           and "@" in group_name, "GROUP_UNREVIEWED")
    groups = Group.objects.filter(name=group_name)
    demand(groups.count() == 1, "GROUP_UNREVIEWED")
    limit = request.get("min_document_id")
    demand(type(limit) is int and limit >= 0, "WATERMARK_INVALID")
    count = request.get("batch_size", 1)
    demand(type(count) is int and 1 <= count <= MAX_BATCH, "BATCH_INVALID")
    samples = request.get("pilot_ids", [])
    demand(isinstance(samples, list) and len(samples) <= MAX_BATCH
           and len(samples) == len(set(samples))
           and all(type(i) is int and i > 0 for i in samples),
           "PILOT_INVALID")
    # AIConfig._get_config_instance() creates a singleton row when absent.
    # A READ_ONLY audit must never trigger that implicit write.
    demand(ApplicationConfiguration.objects.exists(), "APP_CONFIG_MISSING")
    config = AIConfig()
    endpoint = config.llm_endpoint
    expected = request.get("expected_endpoint")
    model = request.get("expected_model")
    demand(isinstance(expected, str) and safe_endpoint(expected),
           "ENDPOINT_NOT_APPROVED")
    demand(isinstance(model, str) and 1 <= len(model) <= 96
           and all(c.isalnum() or c in "._:-" for c in model),
           "MODEL_UNREVIEWED")
    # Native v3.3 ai_classifier can be used directly by this bounded worker
    # with the global Paperless AI/UI master switch OFF. This avoids exposing
    # document chat and archive-wide AI tools to all Paperless users.
    ai_ready = bool(not config.ai_enabled and config.llm_backend == "ollama"
                    and endpoint == expected and config.llm_model == model
                    and config.llm_allow_internal_endpoints
                    and not config.llm_embedding_backend)
    model_ready = bool(ai_ready and ollama_model_available(endpoint, model))
    if apply:
        demand(request.get("approved") is True, "APPROVAL_REQUIRED")
        demand(ai_ready, "AI_CONFIG_NOT_READY")
        demand(dns_is_private(endpoint), "OLLAMA_NETWORK_NOT_PRIVATE")
        demand(model_ready, "OLLAMA_MODEL_UNAVAILABLE")
        demand(limit > 0 or bool(samples), "WATERMARK_REQUIRED")
    return model_ready, groups.first(), count, samples, config


def eligible(doc, group, min_id, pilot):
    if not doc or (not pilot and doc.pk <= min_id):
        return False
    if not doc.owner_id or not doc.owner or not doc.owner.is_active:
        return False
    if doc.owner.is_staff or doc.owner.is_superuser:
        return False
    if not doc.owner.groups.filter(pk=group.pk).exists():
        return False
    if not doc.tags.filter(is_inbox_tag=True).exists():
        return False
    if not doc.content or len(doc.content.strip()) < 30:
        return False
    # Avoid automatic writes into versioned documents whose effective content
    # may come from a separate linked revision.
    if doc.root_document_id is not None or doc.versions.exists():
        return False
    return True


def init_journal():
    parent = JOURNAL_BASE.parent
    demand(parent.is_dir() and not parent.is_symlink(), "DATA_MOUNT_NOT_READY")
    demand(not JOURNAL_BASE.is_symlink(), "JOURNAL_UNSAFE")
    JOURNAL_BASE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(JOURNAL_BASE, 0o700)
    demand(not JOURNAL_DB.is_symlink(), "JOURNAL_UNSAFE")
    old_umask = os.umask(0o077)
    try:
        db = sqlite3.connect(str(JOURNAL_DB), timeout=3)
        os.chmod(JOURNAL_DB, 0o600)
        db.execute("""CREATE TABLE IF NOT EXISTS catalogue (
            document_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT,
            applied_json TEXT
        )""")
        db.commit()
        return db
    finally:
        os.umask(old_umask)


def guarded_document(doc_id, group, min_id, pilot):
    doc = Document.objects.filter(pk=doc_id).select_related("owner").first()
    demand(eligible(doc, group, min_id, pilot), "DOCUMENT_NOT_ELIGIBLE")
    return doc


def resolve_choices(suggestions, owner):
    demand(isinstance(suggestions, dict), "SUGGESTIONS_INVALID")
    tags_choice = suggestions["tags"]
    correspondents = suggestions["correspondents"]
    types = suggestions["document_types"]
    tags = resolve_tags(
        tags_choice["new_names"],
        resolve_tag_ids(tags_choice["existing_ids"], owner)
        + match_tags_by_name(tags_choice["new_names"], owner),
        create_missing=False, owner=owner,
    )
    # Never allow an LLM to suggest the inbox tag itself or an owned tag
    # belonging to someone else. Existing inbox tags remain on the document.
    tags = [tag for tag in tags
            if not tag.is_inbox_tag
            and (tag.owner_id is None or tag.owner_id == owner.pk)]
    correspondent = resolve_object(
        Correspondent, correspondents["new_names"],
        resolve_correspondent_ids(correspondents["existing_ids"], owner)
        + match_correspondents_by_name(correspondents["new_names"], owner),
        create_missing=False, owner=owner,
    )
    kind = resolve_object(
        DocumentType, types["new_names"],
        resolve_document_type_ids(types["existing_ids"], owner)
        + match_document_types_by_name(types["new_names"], owner),
        create_missing=False, owner=owner,
    )
    return tags, correspondent, kind


def process_one(doc_id, group, minimum, pilot, db):
    if db.execute("SELECT 1 FROM catalogue WHERE document_id=?", (doc_id,)).fetchone():
        return "ALREADY_RECORDED"
    doc = guarded_document(doc_id, group, minimum, pilot)
    before = snapshot(doc)
    before_json = stable_snapshot(before)
    db.execute("INSERT INTO catalogue(document_id,state,before_json) VALUES (?,?,?)",
               (doc_id, "PROCESSING", before_json))
    db.commit()
    try:
        # Run upstream v3.3.0's native LLM classifier exactly once.
        # Passing the real owner prevents cross-owner taxonomy lookup.
        suggestions = get_ai_document_classification(doc, doc.owner, None)
        tags, correspondent, kind = resolve_choices(suggestions, doc.owner)
        with transaction.atomic():
            current_doc = Document.objects.select_for_update().get(pk=doc_id)
            demand(eligible(current_doc, group, minimum, pilot), "DOCUMENT_CHANGED")
            demand(stable_snapshot(snapshot(current_doc)) == before_json,
                   "DOCUMENT_CHANGED")
            changes = plan_changes(
                before, suggestions, [t.pk for t in tags],
                correspondent.pk if correspondent else None,
                kind.pk if kind else None,
            )
            if (changes["title"] is None
                and changes["correspondent_id"] is None
                and changes["document_type_id"] is None
                and not changes["add_tag_ids"]):
                raise PolicyError("NO_APPLICABLE_SUGGESTIONS")
            if changes["title"] is not None:
                current_doc.title = changes["title"]
            if changes["correspondent_id"] is not None:
                current_doc.correspondent_id = changes["correspondent_id"]
            if changes["document_type_id"] is not None:
                current_doc.document_type_id = changes["document_type_id"]
            fields = [field for field in ("title", "correspondent", "document_type")
                      if changes[field if field == "title" else field + "_id"] is not None]
            if fields:
                current_doc.save(update_fields=[*fields, "modified"])
            add = [t for t in tags if t.pk in changes["add_tag_ids"]]
            if add:
                current_doc.add_nested_tags(add)
            demand(current_doc.tags.filter(is_inbox_tag=True).exists(),
                   "INBOX_TAG_REMOVED")
            post = snapshot(current_doc)
            # Nested tags may add parent tags; capture all additions precisely
            # for rollback, never remove a previously existing (incl. inbox) tag.
            changes["add_tag_ids"] = sorted(
                set(post["tag_ids"]) - set(before["tag_ids"])
            )
            after = stable_snapshot(post)
        db.execute("UPDATE catalogue SET state=?,after_json=?,applied_json=? WHERE document_id=?",
                   ("APPLIED", after, json.dumps(changes, sort_keys=True), doc_id))
        db.commit()
        return "APPLIED"
    except Exception:
        # Never retry an indeterminate write without a human reviewing
        # the document and the persistent journal. Retain the inbox tag.
        db.execute("UPDATE catalogue SET state=? WHERE document_id=?",
                   ("REQUIRES_REVIEW", doc_id))
        db.commit()
        return "REQUIRES_REVIEW"


def rollback_one(doc_id, group, db):
    row = db.execute(
        "SELECT state,before_json,after_json,applied_json FROM catalogue WHERE document_id=?",
        (doc_id,)
    ).fetchone()
    demand(row and row[0] == "APPLIED" and row[2], "ROLLBACK_UNAVAILABLE")
    before, after, changes = json.loads(row[1]), row[2], json.loads(row[3])
    with transaction.atomic():
        doc = Document.objects.select_for_update().get(pk=doc_id)
        demand(eligible(doc, group, 0, True), "ROLLBACK_REVIEW_REQUIRED")
        demand(stable_snapshot(snapshot(doc)) == after, "ROLLBACK_REVIEW_REQUIRED")
        # Only the recorded metadata is reverted; no document/ACL/storage edits.
        doc.title = before["title"]
        doc.correspondent_id = before["correspondent_id"]
        doc.document_type_id = before["document_type_id"]
        doc.save(update_fields=["title", "correspondent", "document_type", "modified"])
        new_ids = set(doc.tags.values_list("pk", flat=True)) - set(before["tag_ids"])
        allowed_ids = set(changes["add_tag_ids"])
        demand(new_ids <= allowed_ids, "ROLLBACK_REVIEW_REQUIRED")
        doc.tags.remove(*Tag.objects.filter(pk__in=new_ids, is_inbox_tag=False))
        demand(doc.tags.filter(is_inbox_tag=True).exists(), "INBOX_TAG_REMOVED")
    db.execute("UPDATE catalogue SET state=? WHERE document_id=?",
               ("ROLLED_BACK", doc_id))
    db.commit()


def run():
    try:
        request = json.load(sys.stdin)
        mode = request.get("mode") if isinstance(request, dict) else None
        ai_ready, group, count, pilot, cfg = ensure_config(
            request, apply=(mode in ("apply", "rollback"))
        )
        min_id = request["min_document_id"]
        queryset = Document.objects.filter(
            tags__is_inbox_tag=True,
            owner__groups=group,
            owner__is_active=True,
        ).distinct()
        if pilot:
            queryset = queryset.filter(pk__in=pilot)
        else:
            queryset = queryset.filter(pk__gt=min_id)
        candidates = list(queryset.order_by("pk")[:30])
        eligible_count = sum(eligible(d, group, min_id, bool(pilot))
                             for d in candidates)
        if mode in ("audit", "preview"):
            report(AUDIT="READ_ONLY", STATUS="READY" if ai_ready else "AI_CONFIG_NOT_READY",
                   PAPERLESS_VERSION="3.3.0", PROVIDER="OLLAMA_LOCAL_ONLY",
                   EMBEDDINGS="DISABLED" if not cfg.llm_embedding_backend else "CONFIG_UNACCEPTABLE",
                   CANDIDATES_SCAN_BOUND=30, ELIGIBLE_SAMPLE=eligible_count,
                   POSTINGEST_WATERMARK="PRESENT" if min_id else "NOT_SET",
                   CHANGED=False)
            return
        demand(len(pilot) <= count, "PILOT_BATCH_INVALID")
        demand(mode != "rollback" or bool(pilot), "PILOT_REQUIRED")
        with init_journal() as db:
            with open(JOURNAL_BASE / "lock", "a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                ids = list(pilot)
                if not pilot:
                    # Already catalogued documents intentionally stay in inbox.
                    # Skip durable journal entries, otherwise the timer would
                    # select the same reviewed-pending document forever.
                    scan_count = 0
                    for candidate in queryset.order_by("pk").iterator(chunk_size=100):
                        scan_count += 1
                        if scan_count > 2000:
                            break
                        processed = db.execute(
                            "SELECT 1 FROM catalogue WHERE document_id=?",
                            (candidate.pk,),
                        ).fetchone()
                        if processed:
                            continue
                        if eligible(candidate, group, min_id, False):
                            ids.append(candidate.pk)
                            if len(ids) >= count:
                                break
                demand(len(ids) <= count, "BATCH_INVALID")
                if not ids:
                    report(AUDIT="CONTROLLED", STATUS="NO_ELIGIBLE_DOCUMENTS",
                           CHANGED=False)
                    return
                outcomes = []
                for doc_id in ids:
                    if mode == "rollback":
                        rollback_one(doc_id, group, db)
                        outcomes.append("ROLLED_BACK")
                    else:
                        outcomes.append(process_one(doc_id, group, min_id,
                                                    bool(pilot), db))
                report(AUDIT="CONTROLLED", STATUS="COMPLETED",
                       APPLIED=outcomes.count("APPLIED"),
                       REVIEW_REQUIRED=outcomes.count("REQUIRES_REVIEW"),
                       ALREADY_RECORDED=outcomes.count("ALREADY_RECORDED"),
                       ROLLED_BACK=outcomes.count("ROLLED_BACK"),
                       CHANGED=any(x in ("APPLIED", "ROLLED_BACK") for x in outcomes),
                       INBOX_TAG_REMOVAL="NEVER",
                       DOCUMENT_ACL_CHANGES="NEVER")
    except PolicyError as exc:
        allowed = {
            "PAPERLESS_VERSION_UNREVIEWED", "INPUT_INVALID", "MODE_INVALID",
            "GROUP_UNREVIEWED", "WATERMARK_INVALID", "BATCH_INVALID",
            "PILOT_INVALID", "ENDPOINT_NOT_APPROVED", "MODEL_UNREVIEWED",
            "APPROVAL_REQUIRED", "AI_CONFIG_NOT_READY",
            "OLLAMA_NETWORK_NOT_PRIVATE", "WATERMARK_REQUIRED",
            "DATA_MOUNT_NOT_READY", "JOURNAL_UNSAFE", "DOCUMENT_NOT_ELIGIBLE",
            "PILOT_BATCH_INVALID", "PILOT_REQUIRED", "INBOX_REMOVED", "SNAPSHOT_INVALID",
            "ROLLBACK_UNAVAILABLE", "ROLLBACK_REVIEW_REQUIRED",
            "INBOX_TAG_REMOVED", "APP_CONFIG_MISSING", "OLLAMA_MODEL_UNAVAILABLE",
        }
        code = str(exc) if str(exc) in allowed else "POLICY_REJECTED"
        report(AUDIT="FAILED_CLOSED", CODE=code, CHANGED=False)
        raise SystemExit(2)
    except Exception:
        report(AUDIT="FAILED_CLOSED", CODE="UNCLASSIFIED_RUNTIME_FAILURE",
               CHANGED=False)
        raise SystemExit(2)


run()
