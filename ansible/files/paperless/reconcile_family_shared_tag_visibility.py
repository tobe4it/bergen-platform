"""Paperless 3.3.0: one shared tag taxonomy, unchanged document privacy.

Native user-visible tag names (including names originating in private collections)
are intentionally made visible to all members of Familie@bergen.intern, while
private documents remain ACL-isolated. No document, owner, tag assignment,
tag owner, matching setting, or permission other than view_tag is changed.
stdin is a tightly bounded JSON request; stdout contains only aggregate codes.
"""
import hashlib
import json
import sys
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import Document, Tag
from documents.permissions import permitted_document_ids, permitted_object_ids
from guardian.models import GroupObjectPermission
from guardian.shortcuts import assign_perm
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_SHARED_TAG_VISIBILITY_V1:"
GROUP = "Familie@bergen.intern"
PARENTS = ("thomas", "nadja")
CHILD = "Kinder@bergen.intern"
MAX_TAGS = 500
MAX_DOCUMENTS = 5000
MAX_MEMBERS = 8


class Blocked(Exception):
    pass


def require(ok, code):
    if not ok:
        raise Blocked(code)


def emit(status, reason="NONE", **kw):
    output = {
        "AUDIT": "CONTROLLED_APPLY" if kw.get("MODE") == "APPLY" else "READ_ONLY",
        "STATUS": status, "REASON": reason,
        "DOCUMENTS_CHANGED": "NO" if status in ("INSPECTED", "APPLIED") else "NOT_VERIFIED",
        "DOCUMENT_ACLS_CHANGED": "NO" if status in ("INSPECTED", "APPLIED") else "NOT_VERIFIED",
        "TAG_ASSIGNMENTS_CHANGED": "NO" if status in ("INSPECTED", "APPLIED") else "NOT_VERIFIED",
        "TAG_OWNERS_CHANGED": "NO" if status in ("INSPECTED", "APPLIED") else "NOT_VERIFIED",
        **kw,
    }
    print(FRAME + json.dumps(output, sort_keys=True), flush=True)


def digest(rows):
    return hashlib.sha256(repr(tuple(sorted(rows))).encode()).hexdigest()


def snapshot_documents(users):
    """Effective view/change/delete by user plus persistent tag assignment."""
    all_docs = list(Document.objects.values_list("pk", "owner_id", "modified"))
    require(0 < len(all_docs) <= MAX_DOCUMENTS, "DOCUMENT_SCOPE_UNREVIEWED")
    matrix = {}
    for user in users:
        u = User.objects.get(pk=user.pk)
        matrix[u.pk] = tuple(
            tuple(sorted(permitted_document_ids(u, perm=perm)))
            for perm in ("view_document", "change_document", "delete_document")
        )
    group_ct = ContentType.objects.get_for_model(Document)
    group_acl = GroupObjectPermission.objects.filter(content_type=group_ct)
    # Include all existing document group grants, independent of selected users.
    acl_rows = group_acl.values_list("group_id", "permission_id", "object_pk")
    all_through = Document.tags.through.objects.values_list("document_id", "tag_id")
    return digest([
        ("docs", digest(all_docs)),
        ("effective", digest(matrix.items())),
        ("group_acl", digest(acl_rows)),
        ("tags_assigned", digest(all_through)),
    ])


def tag_grants(group, tags):
    ct = ContentType.objects.get_for_model(Tag)
    permission = Permission.objects.get(content_type=ct, codename="view_tag")
    ids = set(GroupObjectPermission.objects.filter(
        group=group, permission=permission, content_type=ct,
    ).values_list("object_pk", flat=True))
    require(all(x.isdecimal() for x in ids), "TAG_OBJECT_GRANTS_UNREVIEWED")
    return {int(x) for x in ids} & set(tags)


def main():
    mode = "AUDIT"
    try:
        raw = sys.stdin.read(2049)
        require(len(raw) <= 2048, "REQUEST_TOO_LARGE")
        req = json.loads(raw)
        require(type(req) is dict and set(req) == {
            "protocol", "mode", "approved", "expected_tag_count",
        } and req.get("protocol") == "paperless-shared-tag-read-v1",
            "REQUEST_UNREVIEWED")
        require(req["mode"] in ("audit", "apply") and
                req["approved"] is (req["mode"] == "apply") and
                type(req["expected_tag_count"]) is int and
                0 <= req["expected_tag_count"] <= MAX_TAGS and
                (req["mode"] != "apply" or req["expected_tag_count"] > 0),
                "APPROVAL_UNREVIEWED")
        mode = req["mode"].upper()
        require(__full_version_str__ == "3.3.0", "VERSION_UNREVIEWED")
        family = Group.objects.get(name=GROUP)
        child = Group.objects.get(name=CHILD)
        users = list(User.objects.filter(
            is_active=True, groups=family,
        ).distinct().order_by("pk"))
        require(3 <= len(users) <= MAX_MEMBERS and
                all(not u.is_superuser and not u.is_staff for u in users),
                "FAMILY_MEMBERSHIP_UNREVIEWED")
        required_parents = [User.objects.get(username=n) for n in PARENTS]
        require(all(u.is_active and u in users and
                    not u.is_staff and not u.is_superuser
                    for u in required_parents), "PARENTS_NOT_IN_FAMILY")
        child_users = list(User.objects.filter(is_active=True, groups=child))
        require(bool(child_users) and
                all(u in users and not u.is_staff and not u.is_superuser
                    for u in child_users), "CHILD_SCOPE_UNREVIEWED")
        require(family.user_set.filter(username__iexact="paperless-sync").count() == 0,
                "SERVICE_ACCOUNT_IN_FAMILY")

        tags = list(Tag.objects.order_by("pk").values_list("pk", "owner_id"))
        require(0 < len(tags) <= MAX_TAGS and
                (req["expected_tag_count"] == 0 or
                 len(tags) == req["expected_tag_count"]),
                "TAG_COUNT_DRIFT")
        tag_ids = {pk for pk, _ in tags}
        require(len(tag_ids) == len(tags), "TAG_SCOPE_INVALID")
        before = snapshot_documents(users)
        metadata_before = digest(tags)
        owners = {u.username: u for u in required_parents}
        thomas_private = set(Document.objects.filter(
            owner=owners["thomas"],
        ).values_list("pk", flat=True)) - set(
            permitted_document_ids(owners["nadja"])
        )
        require(bool(thomas_private), "THOMAS_PRIVATE_SCOPE_NOT_PROVEN")
        expected_group_grants = tag_grants(family, tag_ids)
        before_missing = len(tag_ids - expected_group_grants)
        model_permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Tag),
            codename="view_tag",
        )
        model_missing = not family.permissions.filter(pk=model_permission.pk).exists()
        visible_before = []
        for user in users:
            fresh = User.objects.get(pk=user.pk)
            visible = set(permitted_object_ids(fresh, Tag, "view_tag"))
            visible_before.append(len(visible & tag_ids))

        if mode == "APPLY":
            with transaction.atomic():
                family.permissions.add(model_permission)
                for pk in sorted(tag_ids - expected_group_grants):
                    assign_perm("view_tag", family, Tag.objects.get(pk=pk))

                # Persistently verify all human family members can view tags,
                # without changing access to even one private document.
                current_grants = tag_grants(family, tag_ids)
                require(current_grants == tag_ids, "TAG_GROUP_GRANTS_INCOMPLETE")
                for user in users:
                    fresh = User.objects.get(pk=user.pk)
                    require(fresh.has_perm("documents.view_tag"),
                            "TAG_MODEL_VIEW_NOT_PROVEN")
                    permitted = set(permitted_object_ids(fresh, Tag, "view_tag"))
                    require(tag_ids <= permitted, "TAG_OBJECT_VIEW_NOT_PROVEN")
                require(snapshot_documents(users) == before,
                        "DOCUMENT_SECURITY_DRIFT")
                require(digest(Tag.objects.values_list("pk", "owner_id"))
                        == metadata_before, "TAG_OWNERS_CHANGED")
                check_private = set(Document.objects.filter(
                    owner=owners["thomas"],
                ).values_list("pk", flat=True)) - set(
                    permitted_document_ids(User.objects.get(
                        pk=owners["nadja"].pk,
                    ))
                )
                require(check_private == thomas_private, "THOMAS_PRIVACY_CHANGED")

        emit("APPLIED" if mode == "APPLY" else "INSPECTED",
             MODE=mode, TAGS=len(tag_ids), FAMILY_MEMBERS=len(users),
             CHILD_IDENTITIES=len(child_users),
             PARENTS=2, THOMAS_PRIVATE_DENIED_TO_NADJA=len(thomas_private),
             FAMILY_TAG_MODEL_GRANT_MISSING_BEFORE=model_missing,
             TAG_OBJECT_GRANTS_MISSING_BEFORE=before_missing,
             FAMILY_MIN_VISIBLE_TAGS_BEFORE=min(visible_before),
             FAMILY_MAX_VISIBLE_TAGS_BEFORE=max(visible_before),
             TAG_READ_SCOPE="ALL_FAMILY_MEMBERS",
             NEW_TAGS="REQUIRE_IDEMPOTENT_RECONCILIATION")
    except Blocked as e:
        emit("BLOCKED", str(e), MODE=mode)
    except Exception:
        emit("BLOCKED", "UNCLASSIFIED", MODE=mode)


main()
