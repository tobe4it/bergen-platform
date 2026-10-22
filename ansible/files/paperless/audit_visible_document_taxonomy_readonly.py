"""Read-only Paperless 3.3.0 visible-document metadata ACL audit.

Policy: people must see a DocumentType / Correspondent used by any Document
they are already entitled to view. Does not require a user to see unrelated
private documents, or unrelated taxonomy entries. Prints bounded aggregate
status only; never emits names, IDs or OCR.
"""
import json
import sys

FRAME = "BERGEN_PAPERLESS_VISIBLE_DOCUMENT_TAXONOMY_V1:"
PARENTS = ("thomas", "nadja")
FAMILY = "Familie@bergen.intern"
CHILD = "Kinder@bergen.intern"
ELTERN = "Eltern@bergen.intern"
MAX_USERS = 8
MAX_DOCS = 5000
MAX_TYPES = 500
MAX_CORRESPONDENTS = 1000


class Blocked(Exception):
    pass


def require(test, code):
    if not test:
        raise Blocked(code)


def emit(**fields):
    print(FRAME + json.dumps(dict(
        AUDIT="READ_ONLY", CHANGED=False,
        DOCUMENTS_CHANGED="NO", DOCUMENT_ACLS_CHANGED="NO",
        METADATA_ACLS_CHANGED="NO", **fields,
    ), separators=(",", ":"), sort_keys=True), flush=True)


def main():
    try:
        from django.contrib.auth.models import Group, User
        from django.contrib.contenttypes.models import ContentType
        from guardian.models import GroupObjectPermission
        from documents.models import Document, DocumentType, Correspondent
        from documents.permissions import permitted_document_ids, permitted_object_ids
        from paperless.version import __full_version_str__

        require(__full_version_str__ == "3.3.0", "VERSION_UNREVIEWED")
        family = Group.objects.get(name=FAMILY)
        child = Group.objects.get(name=CHILD)
        eltern = Group.objects.get(name=ELTERN)
        users = list(User.objects.filter(
            is_active=True, groups=family,
        ).distinct().order_by("pk"))
        require(3 <= len(users) <= MAX_USERS and all(
            not u.is_superuser and not u.is_staff for u in users),
            "FAMILY_MEMBERSHIP_UNREVIEWED")
        for username in PARENTS:
            u = User.objects.get(username=username)
            require(u.is_active and u in users and
                    not u.is_staff and not u.is_superuser,
                    "PARENT_MEMBERSHIP_UNREVIEWED")
        kids = list(User.objects.filter(is_active=True, groups=child))
        require(0 < len(kids) <= MAX_USERS and all(
            u in users and not u.is_superuser and not u.is_staff for u in kids),
            "CHILD_MEMBERSHIP_UNREVIEWED")
        require(family.user_set.filter(username__iexact="paperless-sync").count() == 0,
                "TECHNICAL_ACCOUNT_IN_FAMILY")

        docs = list(Document.objects.values_list(
            "pk", "owner_id", "document_type_id", "correspondent_id"
        ))
        require(0 < len(docs) <= MAX_DOCS, "DOCUMENT_POPULATION_UNREVIEWED")
        dmap = {pk: (owner, dtype, correspondent)
                for pk, owner, dtype, correspondent in docs}
        require(len(dmap) == len(docs), "DOCUMENT_ID_MISMATCH")
        types = set(DocumentType.objects.values_list("pk", flat=True))
        corrs = set(Correspondent.objects.values_list("pk", flat=True))
        require(len(types) <= MAX_TYPES and len(corrs) <= MAX_CORRESPONDENTS,
                "METADATA_POPULATION_UNREVIEWED")

        doc_ct = ContentType.objects.get_for_model(Document)
        parent_doc_pks = {int(pk) for pk in GroupObjectPermission.objects.filter(
            group=eltern, content_type=doc_ct,
            permission__codename="view_document",
        ).values_list("object_pk", flat=True)}
        require(parent_doc_pks and parent_doc_pks <= set(dmap),
                "PARENT_DOCUMENT_BOUNDARY_UNREVIEWED")

        user_counts = []
        for user in users:
            visible_docs = set(permitted_document_ids(user)) & set(dmap)
            doc_type_ids = {
                dmap[pk][1] for pk in visible_docs if dmap[pk][1] is not None
            }
            corr_ids = {
                dmap[pk][2] for pk in visible_docs if dmap[pk][2] is not None
            }
            require(doc_type_ids <= types and corr_ids <= corrs,
                    "DOCUMENT_METADATA_REFERENCES_UNRESOLVED")

            visible_types = set(permitted_object_ids(
                user, DocumentType, "view_documenttype",
            ))
            visible_corrs = set(permitted_object_ids(
                user, Correspondent, "view_correspondent",
            ))
            type_gap = doc_type_ids - visible_types
            corr_gap = corr_ids - visible_corrs

            if user in kids:
                require(not (parent_doc_pks & visible_docs),
                        "CHILD_SEES_ELTERN_DOCUMENT")
            user_counts.append(dict(
                DOCUMENTS=len(visible_docs),
                REQUIRED_TYPES=len(doc_type_ids),
                REQUIRED_CORRESPONDENTS=len(corr_ids),
                TYPE_GAPS=len(type_gap),
                CORRESPONDENT_GAPS=len(corr_gap),
                TYPE_MODEL_RIGHT=int(not user.has_perm(
                    "documents.view_documenttype")),
                CORRESPONDENT_MODEL_RIGHT=int(not user.has_perm(
                    "documents.view_correspondent")),
            ))

        thomas = User.objects.get(username=PARENTS[0])
        nadja = User.objects.get(username=PARENTS[1])
        thomas_own = set(Document.objects.filter(
            owner=thomas).values_list("pk", flat=True))
        nadja_allowed = set(permitted_document_ids(nadja))
        private = thomas_own - nadja_allowed
        require(private, "THOMAS_PRIVATE_BOUNDARY_NOT_PROVEN")
        for child_user in kids:
            require(not (private & set(permitted_document_ids(child_user))),
                    "CHILD_SEES_THOMAS_PRIVATE")

        emit(STATUS="INSPECTED", USERS=len(users), CHILD_USERS=len(kids),
             DOCUMENTS=len(docs), DOCUMENT_TYPES=len(types),
             CORRESPONDENTS=len(corrs),
             REQUIRED_TYPE_VIEWS=sum(x["REQUIRED_TYPES"] for x in user_counts),
             REQUIRED_CORRESPONDENT_VIEWS=sum(
                 x["REQUIRED_CORRESPONDENTS"] for x in user_counts),
             TYPE_VIEW_GAPS=sum(x["TYPE_GAPS"] for x in user_counts),
             CORRESPONDENT_VIEW_GAPS=sum(
                 x["CORRESPONDENT_GAPS"] for x in user_counts),
             TYPE_MODEL_RIGHT_MISSING_USERS=sum(
                 x["TYPE_MODEL_RIGHT"] for x in user_counts),
             CORRESPONDENT_MODEL_RIGHT_MISSING_USERS=sum(
                 x["CORRESPONDENT_MODEL_RIGHT"] for x in user_counts),
             MIN_VISIBLE_DOCS=min(x["DOCUMENTS"] for x in user_counts),
             MAX_VISIBLE_DOCS=max(x["DOCUMENTS"] for x in user_counts),
             THOMAS_PRIVATE_DENIED_TO_NADJA=len(private),
             CHILD_SEES_ELTERN_DOCUMENTS=0,
             CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS=0)
    except Blocked as ex:
        emit(STATUS="BLOCKED", REASON=str(ex))
    except Exception:
        emit(STATUS="BLOCKED", REASON="UNCLASSIFIED")


if __name__ == "__main__":
    main()
