"""No-write Paperless 3.3.0 Eltern/Familie child-chat boundary verification.

Consumes reviewed actual source-import document IDs from the separately
verified root-only receipt audit over stdin. Cross-checks group grants and
effective per-user object visibility with and without model-level view.
Never runs a chat, embeds, logs OCR, grants permissions, or prints identifiers.
"""
import json
import sys

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from documents.models import Document
from documents.permissions import has_perms_owner_aware, permitted_document_ids
from guardian.models import GroupObjectPermission
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_CHAT_CHILD_BOUNDARY_V1:"
GROUPS = {"Eltern": "Eltern@bergen.intern", "Familie": "Familie@bergen.intern"}
CHILD_GROUP = "Kinder@bergen.intern"
MAX_INPUT = 120000
MAX_DOCS = 5000
MAX_USERS = 300


def emit(status, **values):
    result = {"AUDIT": "READ_ONLY", "STATUS": status, "CHANGED": False,
              "DOCUMENTS_CHANGED": False, "USER_PERMISSIONS_CHANGED": False,
              "MODEL_INFERENCE": "NO", **values}
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


def grant_ids(group, content_type):
    rows = GroupObjectPermission.objects.filter(
        group=group,
        content_type=content_type,
        permission__content_type=content_type,
        permission__codename__in=("view_document", "change_document"),
    ).values_list("object_pk", flat=True)
    values = set()
    for raw in rows:
        if not isinstance(raw, str) or not raw.isdecimal() or len(raw) > 12:
            raise ValueError("MALFORMED_GRANT")
        values.add(int(raw))
        if len(values) > MAX_DOCS:
            raise ValueError("GRANT_COUNT")
    return values


def main():
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        data = json.loads(raw) if len(raw) <= MAX_INPUT else {}
        if (__full_version_str__ != "3.3.0" or
                not isinstance(data, dict) or
                data.get("protocol") != "native-chat-import-proof-v1"):
            return emit("BLOCKED")
        routes = data.get("document_ids")
        if not isinstance(routes, dict) or set(routes) != set(GROUPS):
            return emit("BLOCKED")
        imported = {}
        for scope, lst in routes.items():
            if (not isinstance(lst, list) or len(lst) > MAX_DOCS or
                    not all(type(x) is int and x > 0 for x in lst) or
                    len(set(lst)) != len(lst)):
                return emit("BLOCKED")
            imported[scope] = set(lst)
        if imported["Eltern"] & imported["Familie"]:
            return emit("BLOCKED")
        if User.objects.count() > MAX_USERS:
            return emit("BLOCKED")
        live_groups = {}
        for scope, name in GROUPS.items():
            found = Group.objects.filter(name=name)
            if found.count() != 1:
                return emit("GROUP_UNREVIEWED")
            live_groups[scope] = found.first()
        child_groups = Group.objects.filter(name=CHILD_GROUP)
        if child_groups.count() != 1:
            return emit("CHILD_GROUP_UNREVIEWED")
        child_group = child_groups.first()
        ct = ContentType.objects.get_for_model(Document)
        parent_grants = grant_ids(live_groups["Eltern"], ct)
        family_grants = grant_ids(live_groups["Familie"], ct)
        if imported["Eltern"] - parent_grants or imported["Familie"] - family_grants:
            return emit("IMPORT_GROUP_ACL_DRIFT")
        # Consider both imported documents and manually added documents that
        # are explicitly made visible to the two group roles.
        parent_ids = imported["Eltern"] | parent_grants
        family_ids = imported["Familie"] | family_grants
        if parent_ids & family_ids:
            return emit("PARENT_FAMILY_SCOPE_OVERLAP")
        all_ids = parent_ids | family_ids
        if len(all_ids) > MAX_DOCS or Document.objects.filter(pk__in=all_ids).count() != len(all_ids):
            return emit("SCOPE_INCOMPLETE")
        if imported["Eltern"] and Document.objects.filter(
            pk__in=imported["Eltern"], owner__username="admin"
        ).count() != len(imported["Eltern"]):
            return emit("IMPORT_OWNER_DRIFT")
        if imported["Familie"] and Document.objects.filter(
            pk__in=imported["Familie"], owner__username="admin"
        ).count() != len(imported["Familie"]):
            return emit("IMPORT_OWNER_DRIFT")
        if not parent_ids:
            return emit("NO_PARENT_SCOPE_PROVEN")
        docs = {
            doc.pk: doc for doc in
            Document.objects.filter(pk__in=all_ids).select_related("owner")
        }
        active_children = list(User.objects.filter(
            is_active=True, groups=child_group
        ).distinct().order_by("pk"))
        if not active_children:
            return emit("NO_ACTIVE_CHILD_ACCOUNTS", PARENT_SCOPE=len(parent_ids),
                        FAMILY_SCOPE=len(family_ids))
        child_has_model_view = 0
        child_superusers = 0
        child_not_family = 0
        child_parent_view_if_granted = 0
        child_parent_view_now = 0
        child_family_view_if_granted = 0
        child_family_view_now = 0
        child_parent_single_doc_allow = 0
        for child in active_children:
            model_view = child.has_perm("documents.view_document")
            child_has_model_view += bool(model_view)
            child_superusers += bool(child.is_superuser)
            child_not_family += not child.groups.filter(pk=live_groups["Familie"].pk).exists()
            # permitted_document_ids() intentionally does NOT gate on model
            # permission. It gives a forward-looking exposure assessment for
            # the day children receive general view_document.
            allowed_ids = set(permitted_document_ids(
                child, perm="view_document"
            ).filter(pk__in=all_ids))
            exposed_parents = parent_ids & allowed_ids
            exposed_family = family_ids & allowed_ids
            child_parent_view_if_granted += len(exposed_parents)
            child_parent_view_now += len(exposed_parents) if model_view else 0
            child_family_view_if_granted += len(exposed_family)
            child_family_view_now += len(exposed_family) if model_view else 0
            # ChatStreamingView's single-document route checks a distinct,
            # guardian-backed path; reject a disagreement between that path
            # and the document ID filter used in archive-wide RAG.
            for document_id in parent_ids:
                if has_perms_owner_aware(child, "view_document", docs[document_id]):
                    child_parent_single_doc_allow += 1
        blocked = bool(
            child_superusers or child_parent_view_if_granted or
            child_parent_single_doc_allow or child_parent_view_now
        )
        emit(
            "INSPECTED",
            SOURCE_IMPORT_PARENTS=len(imported["Eltern"]),
            SOURCE_IMPORT_FAMILY=len(imported["Familie"]),
            PARENT_DOCUMENT_SCOPE=len(parent_ids),
            FAMILY_DOCUMENT_SCOPE=len(family_ids),
            ACTIVE_CHILD_IDENTITIES=len(active_children),
            CHILD_SUPERUSERS=child_superusers,
            CHILD_MISSING_FAMILY_GROUP=child_not_family,
            CHILD_MODEL_VIEW_ENABLED=child_has_model_view,
            CHILD_PARENT_VISIBLE_NOW=child_parent_view_now,
            CHILD_PARENT_VISIBLE_IF_MODEL_VIEW_GRANTED=child_parent_view_if_granted,
            CHILD_PARENT_SINGLE_DOCUMENT_ALLOW=child_parent_single_doc_allow,
            CHILD_FAMILY_VISIBLE_NOW=child_family_view_now,
            CHILD_FAMILY_VISIBLE_IF_MODEL_VIEW_GRANTED=child_family_view_if_granted,
            CHAT_CHILD_PARENT_BOUNDARY="BLOCKED" if blocked else "NEGATIVE_ACL_CHECK_PASSED",
            CHAT_RELEASE_GATE=(
                "BLOCKED_PARENT_ACCESS" if blocked
                else "USER_SESSION_AND_INDEX_TEST_STILL_REQUIRED"
            ),
        )
    except Exception:
        emit("BLOCKED")


main()
