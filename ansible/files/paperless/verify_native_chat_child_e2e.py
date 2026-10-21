"""Controlled Paperless 3.3.0 child chat acceptance.

AUDIT is strictly read-only (no session, inference, or vector-store opens).
LIVE uses ephemeral Django-authenticated sessions for existing child users and
performs real model calls. This does NOT validate the external OIDC login.
All source document IDs remain on Ansible no_log channels. Only bounded
enumerated outcome codes and aggregate counters are emitted.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import sqlite_vec
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from documents.models import Document, PaperlessTask
from documents.permissions import has_perms_owner_aware, permitted_document_ids
from guardian.models import GroupObjectPermission
from paperless.config import AIConfig
from paperless.version import __full_version_str__
from paperless_ai.ai_classifier import get_llm_output_language
from paperless_ai.embedding import get_configured_model_name

FRAME = "BERGEN_PAPERLESS_CHILD_CHAT_E2E_V1:"
PARENT = "Eltern@bergen.intern"
FAMILY = "Familie@bergen.intern"
CHILD = "Kinder@bergen.intern"
MAX_INPUT = 120000
MAX_DOCS = 5000
MAX_CHILDREN = 4
MAX_STREAM_BYTES = 131072
METADATA = "\n\n__PAPERLESS_CHAT_METADATA__"
ENDPOINT = "/api/documents/chat/"


class Blocked(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Blocked(code)


def emit(status, reason="NONE", **fields):
    print(FRAME + json.dumps({
        "AUDIT": "CONTROLLED" if fields.get("MODE") == "LIVE" else "READ_ONLY",
        "STATUS": status, "REASON": reason,
        "DOCUMENTS_CHANGED": False,
        "USER_PERMISSIONS_CHANGED": False,
        "CHAT_RELEASE_GATE": "EXTERNAL_OIDC_SMOKE_TEST_REQUIRED"
            if status == "PASSED_LIVE" else "BLOCKED",
        **fields,
    }, sort_keys=True), flush=True)


def grant_ids(group, content_type):
    ids = set()
    values = GroupObjectPermission.objects.filter(
        group=group, content_type=content_type,
        permission__content_type=content_type,
        permission__codename__in=("view_document", "change_document"),
    ).values_list("object_pk", flat=True)
    for value in values:
        require(isinstance(value, str) and value.isdecimal()
                and len(value) <= 12, "ACL_REFERENCE_INVALID")
        ids.add(int(value))
        require(len(ids) <= MAX_DOCS, "ACL_SCOPE_UNBOUNDED")
    return ids


def verified_scope(proof):
    require(proof.get("protocol") == "native-chat-import-proof-v1",
            "PROVENANCE_UNREVIEWED")
    routes = proof.get("document_ids")
    require(type(routes) is dict and set(routes) == {"Eltern", "Familie"},
            "PROVENANCE_UNREVIEWED")
    imported = {}
    for name, values in routes.items():
        require(type(values) is list and len(values) <= MAX_DOCS
                and all(type(x) is int and x > 0 for x in values)
                and len(values) == len(set(values)), "PROVENANCE_UNREVIEWED")
        imported[name] = set(values)
    groups = {}
    for name, label in (("Eltern", PARENT), ("Familie", FAMILY)):
        candidates = Group.objects.filter(name=label)
        require(candidates.count() == 1, "GROUP_SCOPE_MISSING")
        groups[name] = candidates.first()
    ct = ContentType.objects.get_for_model(Document)
    grants = {name: grant_ids(group, ct) for name, group in groups.items()}
    for name in imported:
        require(imported[name] <= grants[name], "IMPORT_GRANT_DRIFT")
    parents = imported["Eltern"] | grants["Eltern"]
    family = imported["Familie"] | grants["Familie"]
    require(parents and family and not (parents & family), "SCOPE_INCOMPLETE")
    all_ids = parents | family
    require(len(all_ids) <= MAX_DOCS and
            Document.objects.filter(pk__in=all_ids).count() == len(all_ids),
            "SCOPE_INCOMPLETE")
    require(Group.objects.filter(name=CHILD).count() == 1, "CHILD_GROUP_MISSING")
    children = list(User.objects.filter(
        is_active=True, groups__name=CHILD,
    ).distinct().order_by("pk"))
    require(0 < len(children) <= MAX_CHILDREN, "CHILD_ACCOUNTS_UNREVIEWED")
    for user in children:
        require(not user.is_superuser and not user.is_staff and
                not user.groups.filter(name=PARENT).exists() and
                user.groups.filter(name=FAMILY).exists() and
                user.has_perm("documents.view_document"), "CHILD_ROLE_UNSAFE")
        visible = set(permitted_document_ids(
            user, perm="view_document",
        ).values_list("pk", flat=True))
        require(not (visible & parents) and family <= visible,
                "CHILD_SCOPE_UNSAFE")
        require(not any(has_perms_owner_aware(
            user, "view_document", doc,
        ) for doc in Document.objects.filter(pk__in=parents)),
            "PARENT_SINGLE_ROUTE_UNSAFE")
    return parents, family, children


def check_index():
    docs = {str(pk): timestamp.isoformat()
            for pk, timestamp in Document.objects.values_list("pk", "modified")}
    require(0 < len(docs) <= MAX_DOCS, "DOCUMENT_COUNT_UNREVIEWED")
    file = Path(settings.LLM_INDEX_DIR) / "llmindex.db"
    require(file.is_file() and not file.is_symlink()
            and not file.parent.is_symlink(), "INDEX_PATH_UNREVIEWED")
    uri = "file:" + quote(str(file), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        db.execute("PRAGMA query_only=ON")
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        meta = db.execute(
            "SELECT value FROM index_meta WHERE key='embed_model'",
        ).fetchone()
        require(meta is not None and
                meta[0] == get_configured_model_name(AIConfig()),
                "INDEX_MODEL_MISMATCH")
        modified = {str(k): v for k, v in db.execute(
            "SELECT document_id, modified FROM document_meta",
        )}
        chunks = {str(row[0]) for row in db.execute(
            "SELECT DISTINCT document_id FROM document_chunks",
        )}
        chunk_count = db.execute(
            "SELECT COUNT(*) FROM document_chunks",
        ).fetchone()[0]
        vector_count = db.execute(
            "SELECT COUNT(*) FROM documents",
        ).fetchone()[0]
    require(modified == docs and chunks == set(docs)
            and chunk_count == vector_count and chunk_count > 0,
            "INDEX_COVERAGE_DRIFT")
    return docs


def consume_response(response, allowed, parents, require_reference):
    try:
        require(response.status_code == 200 and response.streaming,
                "CHAT_HTTP_UNEXPECTED")
        data = bytearray()
        for chunk in response.streaming_content:
            encoded = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
            require(len(data) + len(encoded) <= MAX_STREAM_BYTES,
                    "CHAT_STREAM_UNBOUNDED")
            data.extend(encoded)
        content = data.decode("utf-8")
        require(METADATA in content, "CHAT_REFERENCES_MISSING")
        answer, trailer = content.rsplit(METADATA, 1)
        require(len(answer.strip()) >= 12
                and not answer.startswith("Sorry,"),
                "CHAT_ANSWER_UNAVAILABLE")
        metadata = json.loads(trailer)
        references = metadata.get("references")
        require(type(references) is list and 0 < len(references) <= 3,
                "CHAT_REFERENCES_INVALID")
        ids = []
        for ref in references:
            require(type(ref) is dict and type(ref.get("id")) is int,
                    "CHAT_REFERENCES_INVALID")
            ids.append(ref["id"])
        require(set(ids) <= allowed and not (set(ids) & parents),
                "CHAT_PARENT_REFERENCE_LEAK")
        require(require_reference is None or require_reference in ids,
                "FAMILY_REFERENCE_MISSING")
        return len(ids)
    finally:
        response.close()


def live_checks(parents, family, children, before_docs):
    from documents import views as views_module

    original = views_module.stream_chat_with_documents
    verified = 0
    host = next((
        name for name in settings.ALLOWED_HOSTS
        if isinstance(name, str) and
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", name)
    ), "testserver")

    for user in children:
        allowed = set(permitted_document_ids(
            user, perm="view_document",
        ).values_list("pk", flat=True))
        seen_routes = []

        def guarded_stream(*args, **kwargs):
            documents = kwargs.get("documents")
            require(documents is not None, "CHAT_ROUTE_UNREVIEWED")
            ids = set(documents.values_list("pk", flat=True))
            require(bool(ids) and ids <= allowed and not (ids & parents)
                    and kwargs.get("unrestricted") is False,
                    "CHAT_ROUTE_UNSAFE")
            seen_routes.append(ids)
            return original(*args, **kwargs)

        require(get_llm_output_language(AIConfig(), user) == "de",
                "OUTPUT_LANGUAGE_NOT_GERMAN")
        client = Client(enforce_csrf_checks=False, HTTP_HOST=host)
        try:
            # Creates and subsequently deletes one ephemeral Django session.
            # Does not exercise external reverse-proxy / OIDC authentication.
            client.force_login(
                user, backend="django.contrib.auth.backends.ModelBackend",
            )
            with patch.object(
                views_module, "stream_chat_with_documents",
                side_effect=guarded_stream,
            ):
                denied = client.post(
                    ENDPOINT,
                    data=json.dumps({
                        "q": "Ist dieses Dokument lesbar?",
                        "document_id": min(parents),
                    }),
                    content_type="application/json",
                )
                require(denied.status_code == 403 and not seen_routes,
                        "PARENT_DIRECT_NOT_DENIED")
                denied.close()

                family_id = min(family)
                positive = client.post(
                    ENDPOINT,
                    data=json.dumps({
                        "q": "Fasse dieses Dokument kurz auf Deutsch zusammen.",
                        "document_id": family_id,
                    }),
                    content_type="application/json",
                )
                require(consume_response(
                    positive, allowed, parents, family_id,
                ) >= 1, "FAMILY_DIRECT_FAILED")
                require(len(seen_routes) == 1 and
                        seen_routes[0] == {family_id},
                        "FAMILY_ROUTE_INCORRECT")

                archive = client.post(
                    ENDPOINT,
                    data=json.dumps({
                        "q": "Welche Themen behandeln die für mich zugänglichen Dokumente? Bitte auf Deutsch antworten.",
                    }),
                    content_type="application/json",
                )
                consume_response(archive, allowed, parents, None)
                require(len(seen_routes) == 2 and
                        seen_routes[1] == allowed,
                        "ARCHIVE_ROUTE_INCORRECT")
                verified += 1
        finally:
            client.logout()

    require({str(pk): modified.isoformat()
             for pk, modified in Document.objects.values_list(
                 "pk", "modified",
             )} == before_docs, "DOCUMENTS_CHANGED_DURING_TEST")
    return verified


def main():
    mode = "AUDIT"
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        require(len(raw) <= MAX_INPUT, "INPUT_UNBOUNDED")
        data = json.loads(raw)
        require(type(data) is dict and
                data.get("protocol") == "native-child-chat-e2e-v1" and
                data.get("mode") in ("audit", "live"), "INPUT_UNREVIEWED")
        mode = data["mode"].upper()
        require(__full_version_str__ == "3.3.0", "VERSION_UNREVIEWED")
        config = AIConfig()
        require(config.ai_enabled is True and
                config.llm_output_language == "de" and
                config.llm_embedding_backend == "ollama" and
                config.llm_embedding_model in ("bge-m3", "bge-m3:latest"),
                "AI_CONFIG_UNREVIEWED")
        require(not PaperlessTask.objects.filter(
            task_type=PaperlessTask.TaskType.LLM_INDEX,
            status__in=(PaperlessTask.Status.PENDING, PaperlessTask.Status.STARTED),
        ).exists(), "INDEX_TASK_IN_PROGRESS")
        require(data.get("approved") is (mode == "LIVE"),
                "APPROVAL_UNREVIEWED")
        parents, family, children = verified_scope(data.get("proof") or {})
        before_docs = check_index()
        if mode == "AUDIT":
            emit("READY", MODE=mode, CHILD_IDENTITIES=len(children),
                 PARENT_DOCUMENTS=len(parents), FAMILY_DOCUMENTS=len(family),
                 INDEXED_DOCUMENTS=len(before_docs),
                 SESSION_CREATED="NO", MODEL_INFERENCE="NO")
            return
        checked = live_checks(parents, family, children, before_docs)
        require(checked == len(children), "CHILD_TEST_INCOMPLETE")
        emit("PASSED_LIVE", MODE=mode, CHILD_IDENTITIES=checked,
             PARENT_DIRECT_DENIED=checked,
             FAMILY_DIRECT_WITH_REFERENCE=checked,
             ARCHIVE_FILTER_WITH_REFERENCE=checked,
             INDEXED_DOCUMENTS=len(before_docs),
             SESSION_CREATED="EPHEMERAL_CLEANED",
             MODEL_INFERENCE="YES",
             EXTERNAL_OIDC_AUTHENTICATION="NOT_TESTED",
             GERMAN_ANSWER_LANGUAGE="MANUAL_REVIEW_REQUIRED")
    except Blocked as exc:
        emit("BLOCKED", str(exc), MODE=mode)
    except Exception:
        emit("BLOCKED", "UNCLASSIFIED", MODE=mode)


main()
