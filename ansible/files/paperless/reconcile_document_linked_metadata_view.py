"""Controlled Paperless-ngx 3.3.0 document-derived metadata VIEW grants.

The only possible writes are direct UserObjectPermission view_documenttype and
view_correspondent grants to already-existing active human family users, for
metadata referenced by documents that the user already can view. No document
ACLs, group/role permissions, object owners, assignments or other rights change.

The default is a read-only audit. An independently backed-up, exact-counter
pinned and explicitly authorized one-time apply can add only missing grants.
Revocation and future automatic reconciliation are NOT implemented here.
"""
import hashlib
import json
import sys

FRAME = "BERGEN_PAPERLESS_DOCUMENT_LINKED_METADATA_GRANTS_V1:"
FAMILY = "Familie@bergen.intern"
CHILD = "Kinder@bergen.intern"
PARENT = "Eltern@bergen.intern"
PARENTS = ("thomas", "nadja")
MAX_USERS = 8
MAX_DOCS = 5000
MAX_TYPES = 500
MAX_CORR = 1000
MAX_INPUT_BYTES = 1600


class Blocked(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Blocked(code)


def fingerprint(items):
    # Private identifiers are intentionally used only in memory, never logged.
    return hashlib.sha256(repr(tuple(sorted(items))).encode("utf-8")).hexdigest()


def report(status, **details):
    print(FRAME + json.dumps(dict(
        STATUS=status,
        DOCUMENTS_CHANGED="NO" if status in ("INSPECTED", "APPLIED") else "NOT_PROVEN",
        DOCUMENT_ACLS_CHANGED="NO" if status in ("INSPECTED", "APPLIED") else "NOT_PROVEN",
        DOCUMENT_TAGS_CHANGED="NO" if status in ("INSPECTED", "APPLIED") else "NOT_PROVEN",
        GROUP_PERMISSIONS_CHANGED="NO" if status in ("INSPECTED", "APPLIED") else "NOT_PROVEN",
        MODEL_PERMISSIONS_CHANGED="NO" if status in ("INSPECTED", "APPLIED") else "NOT_PROVEN",
        METADATA_OWNERS_CHANGED="NO" if status in ("INSPECTED", "APPLIED") else "NOT_PROVEN",
        **details,
    ), sort_keys=True, separators=(",", ":")), flush=True)


def get_request():
    raw = sys.stdin.read(MAX_INPUT_BYTES + 1)
    require(len(raw) <= MAX_INPUT_BYTES, "REQUEST_TOO_LARGE")
    req = json.loads(raw)
    require(type(req) is dict and req.get("protocol") ==
            "paperless-document-linked-metadata-grants-v1" and
            req.get("mode") in ("audit", "apply"), "INPUT_UNREVIEWED")
    if req["mode"] == "audit":
        require(set(req) == {"protocol", "mode", "approved"} and
                req["approved"] is False, "AUDIT_APPROVAL_UNREVIEWED")
    else:
        require(set(req) == {
            "protocol", "mode", "approved", "expected",
        } and req["approved"] is True and
                type(req["expected"]) is dict and set(req["expected"]) == {
                    "documents", "family_users", "type_gaps",
                    "correspondent_gaps", "thomas_private",
                } and all(type(x) is int and x >= 0
                          for x in req["expected"].values()),
                "APPLY_APPROVAL_UNREVIEWED")
    return req


def main():
    mode = "NOT_PROVEN"
    try:
        req = get_request()
        mode = req["mode"].upper()

        from django.contrib.auth.models import User, Group, Permission
        from django.contrib.contenttypes.models import ContentType
        from django.db import transaction
        from guardian.models import GroupObjectPermission, UserObjectPermission
        from guardian.shortcuts import assign_perm
        from paperless.version import __full_version_str__
        from documents.models import Document, DocumentType, Correspondent
        from documents.permissions import permitted_document_ids, permitted_object_ids

        require(__full_version_str__ == "3.3.0", "VERSION_UNREVIEWED")
        family = Group.objects.get(name=FAMILY)
        children_group = Group.objects.get(name=CHILD)
        parent_group = Group.objects.get(name=PARENT)

        docs_qs = Document.objects.all()
        document_rows = tuple(docs_qs.values_list(
            "pk", "owner_id", "document_type_id", "correspondent_id",
            "deleted_at",
        ))
        require(0 < len(document_rows) <= MAX_DOCS, "DOCUMENT_SCOPE_UNREVIEWED")
        docs = {row[0]: row for row in document_rows}
        require(len(docs) == len(document_rows), "DOCUMENT_SCOPE_UNVERIFIED")
        type_rows = tuple(DocumentType.objects.values_list("pk", "owner_id"))
        corr_rows = tuple(Correspondent.objects.values_list("pk", "owner_id"))
        require(len(type_rows) <= MAX_TYPES and len(corr_rows) <= MAX_CORR,
                "METADATA_SCOPE_UNREVIEWED")
        types = {x[0] for x in type_rows}
        corrs = {x[0] for x in corr_rows}

        users = list(User.objects.filter(
            is_active=True, groups=family,
        ).distinct().order_by("pk"))
        require(3 <= len(users) <= MAX_USERS and
                all(not x.is_superuser and not x.is_staff for x in users),
                "FAMILY_USERS_UNREVIEWED")
        named_parents = [User.objects.get(username=name) for name in PARENTS]
        require(all(p in users and p.is_active and not p.is_staff
                    and not p.is_superuser for p in named_parents),
                "PARENT_USERS_UNREVIEWED")
        children = list(User.objects.filter(
            is_active=True, groups=children_group,
        ).distinct().order_by("pk"))
        require(children and len(children) <= MAX_USERS and
                all(c in users and not c.is_staff and not c.is_superuser
                    for c in children), "CHILD_USERS_UNREVIEWED")
        require(family.user_set.filter(username__iexact="paperless-sync").count() == 0,
                "SERVICE_ACCOUNT_IN_FAMILY")

        doc_ct = ContentType.objects.get_for_model(Document)
        type_ct = ContentType.objects.get_for_model(DocumentType)
        corr_ct = ContentType.objects.get_for_model(Correspondent)
        type_perm = Permission.objects.get(
            content_type=type_ct, codename="view_documenttype")
        corr_perm = Permission.objects.get(
            content_type=corr_ct, codename="view_correspondent")
        allowed = {type_ct.pk: type_perm.pk, corr_ct.pk: corr_perm.pk}

        parent_doc_ids = set(
            int(x) for x in GroupObjectPermission.objects.filter(
                content_type=doc_ct, group=parent_group,
                permission__codename="view_document",
            ).values_list("object_pk", flat=True)
        )
        require(parent_doc_ids and parent_doc_ids <= set(docs),
                "PARENT_DOC_SCOPE_UNREVIEWED")

        def policy():
            required_grants = set()
            user_doc_rights = {}
            required_types = required_corrs = 0
            for user in users:
                fresh = User.objects.get(pk=user.pk)
                require(fresh.has_perm("documents.view_documenttype") and
                        fresh.has_perm("documents.view_correspondent"),
                        "TAXONOMY_MODEL_READ_MISSING")
                effective_docs = tuple(
                    frozenset(permitted_document_ids(fresh, perm=perm))
                    for perm in ("view_document", "change_document",
                                 "delete_document")
                )
                user_doc_rights[fresh.pk] = effective_docs
                visible = effective_docs[0] & set(docs)
                if fresh in children:
                    require(not (parent_doc_ids & visible),
                            "CHILD_PARENT_DOC_VISIBLE")
                dtypes = {docs[pk][2] for pk in visible
                          if docs[pk][2] is not None}
                dcorrs = {docs[pk][3] for pk in visible
                          if docs[pk][3] is not None}
                require(dtypes <= types and dcorrs <= corrs,
                        "DOCUMENT_METADATA_REFERENCES_MISSING")
                required_types += len(dtypes)
                required_corrs += len(dcorrs)
                type_visible = set(permitted_object_ids(
                    fresh, DocumentType, "view_documenttype"))
                corr_visible = set(permitted_object_ids(
                    fresh, Correspondent, "view_correspondent"))
                required_grants |= {
                    (fresh.pk, type_perm.pk, str(x)) for x in dtypes - type_visible
                }
                required_grants |= {
                    (fresh.pk, corr_perm.pk, str(x)) for x in dcorrs - corr_visible
                }
            thomas, nadja = named_parents
            private = set(
                Document.objects.filter(owner=thomas)
                .values_list("pk", flat=True)
            ) - user_doc_rights[nadja.pk][0]
            require(private, "THOMAS_PRIVATE_SCOPE_NOT_PROVEN")
            for child in children:
                require(not (private & user_doc_rights[child.pk][0]),
                        "CHILD_THOMAS_PRIVATE_VISIBLE")
            return {
                "gaps": required_grants,
                "type_gaps": sum(1 for x in required_grants if x[1] == type_perm.pk),
                "corr_gaps": sum(1 for x in required_grants if x[1] == corr_perm.pk),
                "required_types": required_types,
                "required_corrs": required_corrs,
                "users": len(users),
                "children": len(children),
                "docs": len(docs),
                "thomas_private": len(private),
                "doc_rights": user_doc_rights,
            }

        def frozen_rows(queryset):
            return fingerprint(queryset)

        def safe_snapshot():
            # All persistent ACLs, not only user effective grants.
            # A drift check catches collateral mutations to related models.
            return dict(
                documents=frozen_rows(Document.objects.values_list(
                    "pk", "owner_id", "document_type_id",
                    "correspondent_id", "deleted_at")),
                document_tags=frozen_rows(Document.tags.through.objects.values_list(
                    "document_id", "tag_id")),
                doc_user_acl=frozen_rows(UserObjectPermission.objects.filter(
                    content_type=doc_ct).values_list(
                    "user_id", "permission_id", "object_pk")),
                doc_group_acl=frozen_rows(GroupObjectPermission.objects.filter(
                    content_type=doc_ct).values_list(
                    "group_id", "permission_id", "object_pk")),
                taxonomy_owners=(frozen_rows(DocumentType.objects.values_list(
                    "pk", "owner_id")), frozen_rows(Correspondent.objects.values_list(
                    "pk", "owner_id"))),
                taxonomy_group_acl=frozen_rows(GroupObjectPermission.objects.filter(
                    content_type__in=[type_ct,corr_ct]).values_list(
                    "group_id", "permission_id", "object_pk")),
                global_user_grants=frozen_rows(User.user_permissions.through.objects.values_list(
                    "user_id", "permission_id")),
                global_group_grants=frozen_rows(Group.permissions.through.objects.values_list(
                    "group_id", "permission_id")),
                group_membership=frozen_rows(User.groups.through.objects.values_list(
                    "user_id", "group_id")),
            )

        def metadata_user_acl():
            return set(UserObjectPermission.objects.filter(
                content_type__in=[type_ct,corr_ct],
            ).values_list("user_id", "permission_id", "object_pk"))

        status = policy()
        before = safe_snapshot()
        existing_meta_acl = metadata_user_acl()
        if mode == "AUDIT":
            report("INSPECTED", MODE="AUDIT", AUDIT="READ_ONLY",
                   CHANGED=False, DOCUMENTS=status["docs"],
                   FAMILY_USERS=status["users"], CHILD_USERS=status["children"],
                   DOCUMENT_TYPES=len(types), CORRESPONDENTS=len(corrs),
                   REQUIRED_TYPE_VIEWS=status["required_types"],
                   REQUIRED_CORRESPONDENT_VIEWS=status["required_corrs"],
                   TYPE_VIEW_GAPS=status["type_gaps"],
                   CORRESPONDENT_VIEW_GAPS=status["corr_gaps"],
                   THOMAS_PRIVATE_DENIED_TO_NADJA=status["thomas_private"],
                   CHILD_SEES_ELTERN_DOCUMENTS=0,
                   CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS=0)
            return

        expected = req["expected"]
        require(expected == {
            "documents": status["docs"], "family_users": status["users"],
            "type_gaps": status["type_gaps"],
            "correspondent_gaps": status["corr_gaps"],
            "thomas_private": status["thomas_private"],
        }, "EXPECTED_LIVE_COUNTS_DRIFT")

        planned = status["gaps"]
        with transaction.atomic():
            # Lock the exact current documented scope before evaluating again.
            locked = tuple(Document.objects.select_for_update()
                           .order_by("pk").values_list("pk", flat=True))
            require(len(locked) == status["docs"] and
                    set(locked) == set(docs),
                    "DOCUMENT_SCOPE_CHANGED_BEFORE_APPLY")
            require(policy()["gaps"] == planned,
                    "DOCUMENT_VISIBLE_METADATA_DRIFT")
            require(safe_snapshot() == before, "SENSITIVE_STATE_CHANGED")
            require(metadata_user_acl() == existing_meta_acl,
                    "METADATA_GRANTS_CHANGED_BEFORE_APPLY")

            for user_id, permission_id, object_pk in sorted(planned):
                if permission_id == type_perm.pk:
                    obj = DocumentType.objects.get(pk=int(object_pk))
                    codename = "view_documenttype"
                else:
                    require(permission_id == corr_perm.pk,
                            "UNEXPECTED_PERMISSION_TARGET")
                    obj = Correspondent.objects.get(pk=int(object_pk))
                    codename = "view_correspondent"
                assign_perm(codename, User.objects.get(pk=user_id), obj)

            require(safe_snapshot() == before, "UNRELATED_STATE_MUTATED")
            require(metadata_user_acl() == existing_meta_acl | planned,
                    "METADATA_PERMISSION_DELTA_UNEXPECTED")
            after = policy()
            require(after["gaps"] == set() and
                    after["doc_rights"] == status["doc_rights"] and
                    after["thomas_private"] == status["thomas_private"] and
                    after["required_types"] == status["required_types"] and
                    after["required_corrs"] == status["required_corrs"],
                    "METADATA_OR_DOCUMENT_POSTCHECK_FAILED")

        report("APPLIED", MODE="APPLY", AUDIT="CONTROLLED_APPLY",
               CHANGED=bool(planned), DOCUMENTS=status["docs"],
               FAMILY_USERS=status["users"], CHILD_USERS=status["children"],
               TYPE_VIEW_GRANTS_CREATED=status["type_gaps"],
               CORRESPONDENT_VIEW_GRANTS_CREATED=status["corr_gaps"],
               TYPE_VIEW_GAPS_AFTER=0, CORRESPONDENT_VIEW_GAPS_AFTER=0,
               THOMAS_PRIVATE_DENIED_TO_NADJA=status["thomas_private"],
               CHILD_SEES_ELTERN_DOCUMENTS=0,
               CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS=0,
               FUTURE_RECONCILIATION="NOT_ENABLED",
               REVOCATION_POLICY="NOT_ENABLED")
    except Blocked as err:
        report("BLOCKED", MODE=mode, REASON=str(err), CHANGED=False)
    except Exception:
        report("BLOCKED", MODE=mode, REASON="UNCLASSIFIED", CHANGED=False)


# Deliberately unguarded: manage.py shell -c does not set __name__ to __main__.
main()
