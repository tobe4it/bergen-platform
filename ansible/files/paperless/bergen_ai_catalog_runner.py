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
from datetime import datetime
from zoneinfo import ZoneInfo
import socket
import sqlite3
import sys
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, IntegerField
from django.db.models.functions import Cast
from guardian.models import GroupObjectPermission
from documents.models import Correspondent, Document, DocumentType, Note, Tag
from documents.workflows.ai import resolve_object, resolve_tags
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__
from paperless_ai.ai_classifier import get_ai_document_classification
from paperless_ai.ai_classifier import (build_prompt_without_rag,
    build_localization_prompt, parse_ai_response)
from paperless_ai.client import AIClient
from paperless_ai.db import db_connection_released
from paperless_ai.matching import _match_names_to_queryset
from paperless_ai.matching import (
    match_correspondents_by_name, match_document_types_by_name,
    match_tags_by_name, resolve_correspondent_ids,
    resolve_document_type_ids, resolve_tag_ids,
)

FRAME = "BERGEN_PAPERLESS_AI_CATALOG_V1:"
JOURNAL_BASE = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1")
JOURNAL_DB = JOURNAL_BASE / "catalog.sqlite3"
MAX_BATCH = 2
IMPORT_CUTOFF = datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
V2_CUTOFF = "2026-10-01"


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
           and request.get("protocol") in ("catalog-v1", "catalog-v2"), "INPUT_INVALID")
    demand(request.get("mode") in ("audit", "preview", "apply", "rollback"),
           "MODE_INVALID")
    all_inbox = request["protocol"] == "catalog-v2"
    if all_inbox:
        demand(request.get("start_added_date") == V2_CUTOFF,
               "CUTOFF_DATE_UNREVIEWED")
        demand(request.get("allowed_group") in (None, ""),
               "GROUP_SCOPE_MUST_BE_UNSET")
        # v2 invokes only classify_v2_no_rag(), never the native similarity
        # retrieval that interprets user=None as unrestricted. Taxonomy
        # candidates and resolution use explicit document group permissions.
        group = None
    else:
        group_name = request.get("allowed_group")
        demand(isinstance(group_name, str) and 1 <= len(group_name) <= 150
               and "@" in group_name, "GROUP_UNREVIEWED")
        groups = Group.objects.filter(name=group_name)
        demand(groups.count() == 1, "GROUP_UNREVIEWED")
        group = groups.first()
    limit = request.get("min_document_id")
    demand(type(limit) is int and limit >= 0, "WATERMARK_INVALID")
    count = request.get("batch_size", 1)
    demand(type(count) is int and 1 <= count <= MAX_BATCH, "BATCH_INVALID")
    demand(type(request.get("notes_enabled", False)) is bool, "NOTES_FLAG_INVALID")
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
    # The native chat may have its separate, strictly local bge-m3 index.
    # This cataloguing worker ALWAYS uses build_prompt_without_rag and NEVER
    # retrieves indexed neighbours. Do not reject its operation merely
    # because Paperless chat has an approved local embedding backend.
    local_index = (not config.llm_embedding_backend or
                   (config.ai_enabled and
                    config.llm_embedding_backend == "ollama" and
                    config.llm_embedding_model in ("bge-m3", "bge-m3:latest")))
    ai_ready = bool(config.llm_backend == "ollama"
                    and endpoint == expected and config.llm_model == model
                    and config.llm_allow_internal_endpoints
                    and local_index)
    model_ready = bool(ai_ready and ollama_model_available(endpoint, model))
    if apply:
        demand(request.get("approved") is True, "APPROVAL_REQUIRED")
        demand(ai_ready, "AI_CONFIG_NOT_READY")
        demand(dns_is_private(endpoint), "OLLAMA_NETWORK_NOT_PRIVATE")
        demand(model_ready, "OLLAMA_MODEL_UNAVAILABLE")
        demand(all_inbox or limit > 0 or bool(samples), "WATERMARK_REQUIRED")
    return model_ready, group, count, samples, config


def eligible(doc, group, min_id, pilot, *, all_inbox=False):
    if not doc:
        return False
    if all_inbox:
        # Import time (added), not document date (created) or document ID.
        if doc.added is None or doc.added < IMPORT_CUTOFF:
            return False
    else:
        if not pilot and doc.pk <= min_id:
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


def guarded_document(doc_id, group, min_id, pilot, *, all_inbox=False):
    doc = Document.objects.filter(pk=doc_id).select_related("owner").first()
    demand(eligible(doc, group, min_id, pilot, all_inbox=all_inbox),
           "DOCUMENT_NOT_ELIGIBLE")
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
            and (tag.owner_id is None or (owner is not None and tag.owner_id == owner.pk))]
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




# v2 deliberately does NOT use upstream get_taxonomy_context / RAG, since
# Paperless 3.3.0 treats user=None as unrestricted for similar-document
# retrieval. Never include another document's OCR or title in an AI prompt.
V2_TAXONOMY = (
    ("tags", Tag, "view_tag", 10),
    ("correspondents", Correspondent, "view_correspondent", 5),
    ("document_types", DocumentType, "view_documenttype", 5),
    ("storage_paths", None, None, 0),
)


def direct_document_group_ids(doc):
    """Only groups explicitly assigned view/change on THIS document."""
    ct = ContentType.objects.get_for_model(Document)
    return frozenset(GroupObjectPermission.objects.filter(
        content_type=ct, object_pk=str(doc.pk),
        permission__codename__in=("view_document", "change_document"),
        permission__content_type=ct,
    ).values_list("group_id", flat=True))


def scoped_taxonomy(model, perm, doc, group_ids, *, exclude_inbox=False):
    """Global, this owner's, or explicitly shared with document's groups.

    No membership-based implicit sharing of another owner's private metadata.
    Group object permissions must be for this taxonomy model and view action.
    This queryset cannot expose another group's private metadata via an
    ownerless Paperless document.
    """
    cond = Q(owner__isnull=True)
    if doc.owner_id:
        cond |= Q(owner_id=doc.owner_id)
    if group_ids:
        ct = ContentType.objects.get_for_model(model)
        group_shared = GroupObjectPermission.objects.filter(
            content_type=ct, permission__content_type=ct,
            permission__codename=perm,
            group_id__in=group_ids,
        ).annotate(object_pk_int=Cast("object_pk", IntegerField()))          .values_list("object_pk_int", flat=True)
        cond |= Q(pk__in=group_shared)
    qs = model.objects.filter(cond).distinct()
    if exclude_inbox:
        qs = qs.filter(is_inbox_tag=False)
    return qs


def taxonomy_candidates_v2(doc, group_ids):
    """One bounded taxonomy hint list; no neighbouring documents or RAG."""
    choices = {}
    for key, model, perm, cap in V2_TAXONOMY:
        if model is None:
            choices[key] = []
            continue
        qs = scoped_taxonomy(
            model, perm, doc, group_ids, exclude_inbox=(model is Tag)
        )
        choices[key] = [
            {"id": item.pk, "name": item.name, "weight": 1.0}
            for item in qs.order_by("pk")[:cap]
        ]
    return choices


def classify_v2_no_rag(doc, group_ids):
    """Native Paperless LLM and prompt validation, without cross-doc lookup.

    Do not invoke get_ai_document_classification(): its user=None path
    searches unrestricted document OCR. This calls only the *no-RAG* prompt
    builder for the current document and bounded, explicitly visible taxonomy.
    """
    candidates = taxonomy_candidates_v2(doc, group_ids)
    allowed = {
        key: {item["id"] for item in candidates[key]}
        for key in ("tags", "correspondents", "document_types", "storage_paths")
    }
    prompt = build_prompt_without_rag(doc, AIConfig(), candidates=candidates)
    # Keep Paperless's schema, current-document-only prompt, and existing ID
    # matching. Localization is a SECOND isolated Paperless LLM call. IDs,
    # correspondent names and dates always come from the original parse.
    client = AIClient()
    with db_connection_released():
        raw = client.run_llm_query(prompt, allowed_candidate_ids=allowed)
        result = parse_ai_response(raw)
        localized_raw = client.run_llm_query(
            build_localization_prompt(result, "de")
        )
        localized = parse_ai_response(localized_raw)
    output = dict(result)
    output["title"] = localized["title"] or result["title"]
    for field in ("tags", "document_types", "storage_paths"):
        output[field] = {
            "existing_ids": result[field]["existing_ids"],
            "new_names": localized[field]["new_names"]
            or result[field]["new_names"],
        }
    # Proper names and organizational/legal names remain unchanged.
    output["correspondents"] = result["correspondents"]
    output["dates"] = result["dates"]
    return output


def resolve_choices_v2(suggestions, doc, group_ids):
    """Resolve global/owner/group-visible metadata, never invent taxonomy."""
    demand(isinstance(suggestions, dict), "SUGGESTIONS_INVALID")
    selections = {}
    for key, model, perm, _ in V2_TAXONOMY:
        if model is None:
            continue
        block = suggestions.get(key)
        demand(isinstance(block, dict), "SUGGESTIONS_INVALID")
        provided_ids = block.get("existing_ids")
        names = block.get("new_names")
        demand(isinstance(provided_ids, list) and len(provided_ids) <= 20
               and all(type(x) is int and x > 0 for x in provided_ids),
               "SUGGESTIONS_INVALID")
        bounded_ai_labels(names)
        visible = scoped_taxonomy(
            model, perm, doc, group_ids, exclude_inbox=(model is Tag)
        )
        # Even if an LLM returns an unexpected database ID, it cannot
        # override the document's group/owner/global taxonomy scope.
        found_ids = list(visible.filter(pk__in=provided_ids).order_by("pk"))
        found_names = _match_names_to_queryset(names, visible)
        selected = list(dict((obj.pk, obj) for obj in found_ids + found_names).values())
        selections[key] = selected
    return (
        selections["tags"][:10],
        selections["correspondents"][0] if selections["correspondents"] else None,
        selections["document_types"][0] if selections["document_types"] else None,
    )


def verify_choices_v2(doc, group_ids, tags, correspondent, kind):
    """Recheck ACL-backed taxonomy after inference and under document lock."""
    # add_nested_tags() implicitly adds each chosen Tag's parents.
    # Require the parent chain to be equally visible: a visible leaf must
    # not cause a private ancestor Tag to appear on a shared document.
    all_tag_ids = set()
    for tag in tags:
        all_tag_ids.add(tag.pk)
        all_tag_ids.update(tag.get_ancestors_pks())
    if all_tag_ids:
        visible_ids = set(scoped_taxonomy(
            Tag, "view_tag", doc, group_ids, exclude_inbox=True
        ).filter(pk__in=all_tag_ids).values_list("pk", flat=True))
        if visible_ids != all_tag_ids:
            return False
    if correspondent is not None and not scoped_taxonomy(
        Correspondent, "view_correspondent", doc, group_ids
    ).filter(pk=correspondent.pk).exists():
        return False
    if kind is not None and not scoped_taxonomy(
        DocumentType, "view_documenttype", doc, group_ids
    ).filter(pk=kind.pk).exists():
        return False
    return True


def process_one(doc_id, group, minimum, pilot, db, *, notes_enabled=False,
                all_inbox=False):
    # All journal states (including review and no-change) are terminal from
    # the scheduler's perspective. Never replay an uncertain write.
    if db.execute("SELECT 1 FROM catalogue WHERE document_id=?", (doc_id,)).fetchone():
        return "ALREADY_RECORDED", 0, "NONE", "NONE"
    doc = guarded_document(doc_id, group, minimum, pilot, all_inbox=all_inbox)
    before = snapshot(doc)
    before_json = stable_snapshot(before)
    before_groups = direct_document_group_ids(doc) if all_inbox else frozenset()
    db.execute("INSERT INTO catalogue(document_id,state,before_json) VALUES (?,?,?)",
               (doc_id, "PROCESSING", before_json))
    db.commit()
    stage = "INFERENCE"
    try:
        # No RAG and no unbounded user=None in v2. The local model receives
        # this document only plus its explicitly visible taxonomy candidates.
        suggestions = (
            classify_v2_no_rag(doc, before_groups) if all_inbox
            else get_ai_document_classification(doc, doc.owner, None)
        )
        stage = "RESOLUTION"
        tags, correspondent, kind = (
            resolve_choices_v2(suggestions, doc, before_groups) if all_inbox
            else resolve_choices(suggestions, doc.owner)
        )
        # This is only a suggestion rendered for the SAME document owner.
        # Do not include OCR, filenames, prompts or other owners' metadata.
        note_body = (review_note_text(
            suggestions,
            resolved_type_name=kind.name if kind else None,
            resolved_tag_names=[t.name for t in tags],
        ) if notes_enabled else None)

        stage = "VALIDATION"
        notes_added = 0
        with transaction.atomic():
            current_doc = Document.objects.select_for_update().get(pk=doc_id)
            demand(eligible(current_doc, group, minimum, pilot,
                            all_inbox=all_inbox), "DOCUMENT_CHANGED")
            demand(stable_snapshot(snapshot(current_doc)) == before_json,
                   "DOCUMENT_CHANGED")
            if all_inbox:
                current_groups = direct_document_group_ids(current_doc)
                demand(current_groups == before_groups, "DOCUMENT_ACL_CHANGED")
                demand(verify_choices_v2(current_doc, current_groups, tags,
                                         correspondent, kind),
                       "TAXONOMY_ACL_CHANGED")
            changes = plan_changes(
                before, suggestions, [t.pk for t in tags],
                correspondent.pk if correspondent else None,
                kind.pk if kind else None,
            )
            has_changes = has_metadata_changes(changes)
            # Successful classification with an empty permissible diff is NOT
            # an AI failure. Protect manual metadata and keep its inbox tag.
            if notes_enabled and not all_inbox:
                demand(doc.owner.has_perm("documents.add_note"),
                       "NOTE_PERMISSION_DENIED")
            stage = "DB_WRITE"
            if has_changes:
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
            if notes_enabled:
                # Native note model, no privileged API key or admin user.
                # An atomic failure must roll back the metadata as well.
                Note.objects.create(document=current_doc,
                                    user=None if all_inbox else doc.owner,
                                    note=note_body)
                notes_added = 1
            demand(current_doc.tags.filter(is_inbox_tag=True).exists(),
                   "INBOX_TAG_REMOVED")
            post = snapshot(current_doc)
            # Do not permit note creation to rewrite unrelated document
            # fields. At rest, keep the regular optimistic metadata snapshot.
            demand(post["owner_id"] == before["owner_id"]
                   and post["checksum"] == before["checksum"]
                   and post["content_sha256"] == before["content_sha256"]
                   and post["created"] == before["created"]
                   and post["original_filename"] == before["original_filename"]
                   and post["storage_path_id"] == before["storage_path_id"],
                   "UNEXPECTED_DOCUMENT_CHANGE")
            # Nested tags may add parents: record them for guarded rollback.
            changes["add_tag_ids"] = sorted(
                set(post["tag_ids"]) - set(before["tag_ids"])
            )
            after = stable_snapshot(post)
            # Native Paperless Note writes cannot be silently undone by our
            # existing metadata-only rollback route.
            changes["review_note_created"] = bool(notes_added)
            state = "APPLIED" if has_changes else "NO_CHANGE"
        stage = "JOURNAL"
        db.execute(
            "UPDATE catalogue SET state=?,after_json=?,applied_json=? WHERE document_id=?",
            (state, after, json.dumps(changes, sort_keys=True), doc_id),
        )
        db.commit()
        return state, notes_added, "NONE", "NONE"
    except Exception as exc:
        # Store only allowlisted failure *classifications*, never exception
        # strings, model output, title, OCR or identifiers. In particular,
        # write-indeterminate failures remain REQUIRES_REVIEW; no retry.
        allowlisted = {
            "DOCUMENT_CHANGED", "INBOX_TAG_REMOVED", "SNAPSHOT_INVALID",
            "UNEXPECTED_DOCUMENT_CHANGE", "NOTE_PERMISSION_DENIED",
            "NOTE_SUGGESTIONS_INVALID", "CHANGES_INVALID", "SUGGESTIONS_INVALID",
            "TAGS_INVALID", "INBOX_REMOVED", "CORRESPONDENT_INVALID",
            "DOCUMENT_TYPE_INVALID", "DOCUMENT_ACL_CHANGED",
            "TAXONOMY_ACL_CHANGED",
        }
        code = str(exc) if isinstance(exc, PolicyError) and str(exc) in allowlisted else {
            "INFERENCE": "LLM_FAILURE",
            "RESOLUTION": "MATCHING_FAILURE",
            "VALIDATION": "VALIDATION_FAILURE",
            "DB_WRITE": "PERSISTENCE_FAILURE",
            "JOURNAL": "JOURNAL_COMMIT_FAILURE",
        }.get(stage, "UNCLASSIFIED_FAILURE")
        db.execute("UPDATE catalogue SET state=?,applied_json=? WHERE document_id=?",
                   ("REQUIRES_REVIEW",
                    json.dumps({"error_stage": stage, "error_code": code},
                               sort_keys=True), doc_id))
        db.commit()
        return "REQUIRES_REVIEW", 0, stage, code


def rollback_one(doc_id, group, db, *, all_inbox=False):
    row = db.execute(
        "SELECT state,before_json,after_json,applied_json FROM catalogue WHERE document_id=?",
        (doc_id,)
    ).fetchone()
    demand(row and row[0] == "APPLIED" and row[2], "ROLLBACK_UNAVAILABLE")
    before, after, changes = json.loads(row[1]), row[2], json.loads(row[3])
    demand(not changes.get("review_note_created", False),
           "ROLLBACK_REVIEW_REQUIRED")
    with transaction.atomic():
        doc = Document.objects.select_for_update().get(pk=doc_id)
        demand(eligible(doc, group, 0, True,
                        all_inbox=all_inbox), "ROLLBACK_REVIEW_REQUIRED")
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
        all_inbox = request["protocol"] == "catalog-v2"
        if all_inbox:
            queryset = Document.objects.filter(
                tags__is_inbox_tag=True,
                added__gte=IMPORT_CUTOFF,
            ).distinct()
        else:
            queryset = Document.objects.filter(
                tags__is_inbox_tag=True,
                owner__groups=group,
                owner__is_active=True,
            ).distinct()
        if pilot:
            queryset = queryset.filter(pk__in=pilot)
        elif not all_inbox:
            queryset = queryset.filter(pk__gt=min_id)
        candidates = list(queryset.order_by("pk")[:30])
        eligible_count = sum(eligible(d, group, min_id, bool(pilot),
                                      all_inbox=all_inbox)
                             for d in candidates)
        if mode in ("audit", "preview"):
            report(AUDIT="READ_ONLY", STATUS="READY" if ai_ready else "AI_CONFIG_NOT_READY",
                   PAPERLESS_VERSION="3.3.0", PROVIDER="OLLAMA_LOCAL_ONLY",
                   EMBEDDINGS="LOCAL_OLLAMA_BGE_M3" if cfg.llm_embedding_backend == "ollama" and cfg.llm_embedding_model in ("bge-m3", "bge-m3:latest") else ("DISABLED" if not cfg.llm_embedding_backend else "CONFIG_UNACCEPTABLE"),
                   CANDIDATES_SCAN_BOUND=30, ELIGIBLE_SAMPLE=eligible_count,
                   POSTINGEST_WATERMARK="NOT_USED" if all_inbox else ("PRESENT" if min_id else "NOT_SET"),
                   SELECTION_SCOPE="ALL_INBOX_FROM_2026_10_01" if all_inbox else "PARENT_POST_WATERMARK",
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
                        if eligible(candidate, group, min_id, False,
                                    all_inbox=all_inbox):
                            ids.append(candidate.pk)
                            if len(ids) >= count:
                                break
                demand(len(ids) <= count, "BATCH_INVALID")
                if not ids:
                    report(AUDIT="CONTROLLED", STATUS="NO_ELIGIBLE_DOCUMENTS",
                           CHANGED=False)
                    return
                outcomes = []
                notes_added = 0
                failures = []
                for doc_id in ids:
                    if mode == "rollback":
                        rollback_one(doc_id, group, db, all_inbox=all_inbox)
                        outcomes.append("ROLLED_BACK")
                    else:
                        outcome, note_count, failure_stage, failure_code = process_one(
                            doc_id, group, min_id, bool(pilot), db,
                            notes_enabled=request.get("notes_enabled", False),
                            all_inbox=all_inbox,
                        )
                        outcomes.append(outcome)
                        notes_added += note_count
                        if outcome == "REQUIRES_REVIEW":
                            failures.append((failure_stage, failure_code))
                report(AUDIT="CONTROLLED", STATUS="COMPLETED",
                       APPLIED=outcomes.count("APPLIED"),
                       NO_CHANGE=outcomes.count("NO_CHANGE"),
                       NOTES_ADDED=notes_added,
                       ERROR_STAGE=failures[0][0] if failures else "NONE",
                       ERROR_CODE=failures[0][1] if failures else "NONE",
                       REVIEW_REQUIRED=outcomes.count("REQUIRES_REVIEW"),
                       ALREADY_RECORDED=outcomes.count("ALREADY_RECORDED"),
                       ROLLED_BACK=outcomes.count("ROLLED_BACK"),
                       CHANGED=notes_added > 0 or any(x in ("APPLIED", "ROLLED_BACK") for x in outcomes),
                       INBOX_TAG_REMOVAL="NEVER",
                       DOCUMENT_ACL_CHANGES="NEVER",
                       SELECTION_SCOPE="ALL_INBOX_FROM_2026_10_01" if all_inbox else "PARENT_POST_WATERMARK")
    except PolicyError as exc:
        allowed = {
            "PAPERLESS_VERSION_UNREVIEWED", "INPUT_INVALID", "MODE_INVALID",
            "GROUP_UNREVIEWED", "WATERMARK_INVALID", "BATCH_INVALID",
            "PILOT_INVALID", "ENDPOINT_NOT_APPROVED", "MODEL_UNREVIEWED",
            "APPROVAL_REQUIRED", "AI_CONFIG_NOT_READY",
            "OLLAMA_NETWORK_NOT_PRIVATE", "WATERMARK_REQUIRED",
            "DATA_MOUNT_NOT_READY", "JOURNAL_UNSAFE", "DOCUMENT_NOT_ELIGIBLE",
            "PILOT_BATCH_INVALID", "PILOT_REQUIRED", "INBOX_REMOVED", "SNAPSHOT_INVALID",
            "CUTOFF_DATE_UNREVIEWED", "GROUP_SCOPE_MUST_BE_UNSET",
            "GROUP_ACL_CONTEXT_UNVERIFIED",
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
