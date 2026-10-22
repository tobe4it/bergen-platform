"""Bergen Paperless 3.3.0: provenance-safe native taxonomy VIEW reconciliation.

No-write by default. Production apply is an explicit, backed-up, five-counter
pinned transaction. Only engine-created grants enter its private DB ledger;
historic manual grants are never adopted and never revoked.

No document ACL/ownership, tag assignments, external groups, global/model
permissions, metadata ownership, change/delete permission or content edits.
"""
import hashlib
import json
import re
import sys

FRAME = "BERGEN_PAPERLESS_METADATA_RECONCILER_V1:"
LEDGER = "public.bergen_platform_paperless_acl_grants_v1"
COMMENT = "bergen-platform-paperless-managed-metadata-view-v1"
FAMILY = "Familie@bergen.intern"
CHILDREN = "Kinder@bergen.intern"
ELTERN = "Eltern@bergen.intern"
PARENTS = ("thomas", "nadja")
MAX_USERS = 8
MAX_DOCS = 5000
MAX_TAGS = 500
MAX_TYPES = 500
MAX_CORR = 1000
MAX_LEDGER = 10000
LOCK_KEY = 67423108712046
PROTOCOL = "bergen-paperless-metadata-reconciler-v1"


class Refusal(Exception):
    pass


def require(test, reason):
    if not test:
        raise Refusal(reason)


def digest(rows):
    return hashlib.sha256(repr(tuple(sorted(rows))).encode("utf-8")).hexdigest()


def delta(required, actual, managed):
    """Do not adopt pre-existing grants; revoke only exact previously managed."""
    # required is a policy set of exact (kind, subject_id, permission_id, pk)
    return required - actual, managed - required


def frame(status, **kw):
    payload = dict(STATUS=status, **kw)
    message = FRAME + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    require(len(message) < 1800, "REPORT_UNBOUNDED")
    print(message, flush=True)


def request():
    data = sys.stdin.read(1301)
    require(len(data) <= 1300, "REQUEST_TOO_LARGE")
    obj = json.loads(data)
    require(type(obj) is dict and obj.get("protocol") == PROTOCOL and
            obj.get("mode") in ("audit", "apply"), "REQUEST_UNREVIEWED")
    if obj["mode"] == "audit":
        require(set(obj) == {"protocol", "mode", "approved"} and
                obj["approved"] is False, "AUDIT_GATE_UNREVIEWED")
    else:
        expected = obj.get("expected")
        keys = {"documents", "users", "tags", "type_gaps", "corr_gaps",
                "tag_gaps", "managed_revocations", "thomas_private"}
        require(set(obj) == {"protocol", "mode", "approved", "expected"} and
                obj["approved"] is True and type(expected) is dict and
                set(expected) == keys and all(type(x) is int and 0 <= x <= 10000
                                              for x in expected.values()),
                "APPLY_GATE_UNREVIEWED")
    return obj


def main():
    mode = "UNKNOWN"
    try:
        req = request()
        mode = req["mode"].upper()
        from django.contrib.auth.models import Group, User, Permission
        from django.contrib.contenttypes.models import ContentType
        from django.db import connection, transaction
        from guardian.models import GroupObjectPermission, UserObjectPermission
        from documents.models import Document, Tag, DocumentType, Correspondent
        from documents.permissions import permitted_document_ids, permitted_object_ids
        from paperless.version import __full_version_str__

        require(__full_version_str__ == "3.3.0", "VERSION_UNREVIEWED")
        require(connection.vendor == "postgresql", "DATABASE_UNREVIEWED")
        fam = Group.objects.get(name=FAMILY)
        cg = Group.objects.get(name=CHILDREN)
        pg = Group.objects.get(name=ELTERN)
        parents = [User.objects.get(username=u) for u in PARENTS]
        users = list(User.objects.filter(is_active=True, groups=fam)
                     .distinct().order_by("pk"))
        children = list(User.objects.filter(is_active=True, groups=cg).distinct())
        require(3 <= len(users) <= MAX_USERS and children and
                len(children) <= MAX_USERS and
                all(x in users and not x.is_staff and not x.is_superuser
                    for x in parents + children) and
                all(not x.is_staff and not x.is_superuser for x in users),
                "FAMILY_MEMBERSHIP_UNREVIEWED")
        require(not fam.user_set.filter(username__iexact="paperless-sync").exists(),
                "SERVICE_ACCOUNT_IN_FAMILY")
        doc_ct = ContentType.objects.get_for_model(Document)
        tag_ct = ContentType.objects.get_for_model(Tag)
        type_ct = ContentType.objects.get_for_model(DocumentType)
        corr_ct = ContentType.objects.get_for_model(Correspondent)
        tag_perm = Permission.objects.get(content_type=tag_ct, codename="view_tag")
        type_perm = Permission.objects.get(content_type=type_ct,
                                           codename="view_documenttype")
        corr_perm = Permission.objects.get(content_type=corr_ct,
                                           codename="view_correspondent")
        targets = {tag_perm.id: ("group", tag_ct.id),
                   type_perm.id: ("user", type_ct.id),
                   corr_perm.id: ("user", corr_ct.id)}
        require(len(targets) == 3, "PERMISSION_TARGET_UNREVIEWED")

        def protected():
            # Do not include the specifically allowed VIEW grants in this
            # fingerprint. Everything else, including native document grants,
            # document/tag links, global roles and membership, must be fixed.
            rows = (
                digest(Document.objects.values_list(
                    "pk", "owner_id", "document_type_id", "correspondent_id",
                    "deleted_at")),
                digest(Document.tags.through.objects.values_list(
                    "document_id", "tag_id")),
                digest(UserObjectPermission.objects.filter(
                    content_type=doc_ct).values_list(
                    "user_id", "permission_id", "object_pk")),
                digest(GroupObjectPermission.objects.filter(
                    content_type=doc_ct).values_list(
                    "group_id", "permission_id", "object_pk")),
                digest(GroupObjectPermission.objects.exclude(
                    permission_id=tag_perm.id, group_id=fam.id).values_list(
                    "group_id", "permission_id", "content_type_id", "object_pk")),
                digest(UserObjectPermission.objects.exclude(
                    permission_id__in=[type_perm.id,corr_perm.id]).values_list(
                    "user_id", "permission_id", "content_type_id", "object_pk")),
                digest(User.user_permissions.through.objects.values_list(
                    "user_id", "permission_id")),
                digest(Group.permissions.through.objects.values_list(
                    "group_id", "permission_id")),
                digest(User.groups.through.objects.values_list(
                    "user_id", "group_id")),
                digest(Tag.objects.values_list("pk", "owner_id")),
                digest(DocumentType.objects.values_list("pk", "owner_id")),
                digest(Correspondent.objects.values_list("pk", "owner_id")),
            )
            return digest(enumerate(rows))

        def ledger_available(cur):
            cur.execute("SELECT current_schema(), to_regclass(%s)",
                        [LEDGER])
            schema, regclass = cur.fetchone()
            require(schema == "public", "DATABASE_SCHEMA_UNREVIEWED")
            if regclass is None:
                return False
            cur.execute("SELECT obj_description(%s::regclass)", [LEDGER])
            require(cur.fetchone()[0] == COMMENT, "LEDGER_OWNER_UNVERIFIED")
            return True

        def ledger_rows(cur, present):
            if not present:
                return set()
            cur.execute(
                "SELECT subject_kind, subject_id, permission_id, object_pk "
                "FROM " + LEDGER)
            rows = {(kind, int(subject), int(perm), obj)
                    for kind, subject, perm, obj in cur.fetchall()}
            require(len(rows) <= MAX_LEDGER, "LEDGER_TOO_LARGE")
            require(all(x[2] in targets and x[0] == targets[x[2]][0] and
                        x[1] > 0 and re.fullmatch(r"[1-9][0-9]*", x[3])
                        for x in rows),
                    "LEDGER_CONTENT_UNREVIEWED")
            return rows

        def present_grants():
            # Only *explicit* guardian grants are managed, not owner/unowned
            # visibility or broad model grants. Never adopt existing rows.
            gr = {("group", fam.id, tag_perm.id, str(x))
                  for x in GroupObjectPermission.objects.filter(
                      group=fam, permission=tag_perm, content_type=tag_ct
                  ).values_list("object_pk", flat=True)}
            ur = {("user", u, p, str(pk))
                  for u, p, pk in UserObjectPermission.objects.filter(
                      permission_id__in=[type_perm.id, corr_perm.id]
                  ).values_list("user_id", "permission_id", "object_pk")}
            return gr | ur

        def policy(managed):
            docs = list(Document.objects.values_list(
                "pk", "owner_id", "document_type_id", "correspondent_id"))
            require(0 < len(docs) <= MAX_DOCS, "DOCUMENT_POPULATION_UNREVIEWED")
            dmap = {x[0]: x for x in docs}
            tags = set(Tag.objects.values_list("pk", flat=True))
            dtypes = set(DocumentType.objects.values_list("pk", flat=True))
            corrs = set(Correspondent.objects.values_list("pk", flat=True))
            require(len(dmap) == len(docs) and len(tags) <= MAX_TAGS and
                    len(dtypes) <= MAX_TYPES and len(corrs) <= MAX_CORR,
                    "TAXONOMY_POPULATION_UNREVIEWED")
            parent_docs = {int(x) for x in GroupObjectPermission.objects.filter(
                group=pg, content_type=doc_ct,
                permission__codename="view_document",
            ).values_list("object_pk", flat=True)}
            require(parent_docs and parent_docs <= set(dmap),
                    "PARENT_DOCUMENT_SCOPE_UNREVIEWED")
            required = {("group", fam.id, tag_perm.id, str(pk)) for pk in tags}
            rights = {}
            totals = {"docs":len(docs), "users":len(users), "tags":len(tags)}
            for user in users:
                fresh = User.objects.get(pk=user.pk)
                require(all(fresh.has_perm(p) for p in (
                    "documents.view_tag",
                    "documents.view_documenttype",
                    "documents.view_correspondent",
                )), "METADATA_MODEL_PERMISSIONS_MISSING")
                effective = tuple(frozenset(permitted_document_ids(
                    fresh, perm=p)) for p in ("view_document", "change_document",
                                              "delete_document"))
                rights[fresh.pk] = effective
                visible = effective[0] & set(dmap)
                if fresh in children:
                    require(not (visible & parent_docs),
                            "CHILD_SEES_ELTERN_DOCUMENT")
                user_types = {dmap[d][2] for d in visible if dmap[d][2] is not None}
                user_corrs = {dmap[d][3] for d in visible if dmap[d][3] is not None}
                require(user_types <= dtypes and user_corrs <= corrs,
                        "DOCUMENT_METADATA_UNRESOLVED")
                visible_types = set(permitted_object_ids(
                    fresh, DocumentType, "view_documenttype"))
                visible_corrs = set(permitted_object_ids(
                    fresh, Correspondent, "view_correspondent"))
                # Keep managed grants needed by visible documents even if
                # another owner-based access path now also provides visibility.
                required |= {("user", fresh.pk, type_perm.id, str(x))
                             for x in user_types - visible_types}
                required |= {("user", fresh.pk, corr_perm.id, str(x))
                             for x in user_corrs - visible_corrs}
                required |= {entry for entry in managed if entry[0] == "user"
                             and entry[1] == fresh.pk and
                             ((entry[2] == type_perm.id and int(entry[3]) in user_types)
                              or (entry[2] == corr_perm.id
                                  and int(entry[3]) in user_corrs))}
            thomas, nadja = parents
            private = set(Document.objects.filter(
                owner=thomas).values_list("pk", flat=True)) - rights[nadja.pk][0]
            require(private, "THOMAS_PRIVATE_NOT_PROVEN")
            require(all(not (private & rights[x.pk][0]) for x in children),
                    "CHILD_SEES_THOMAS_PRIVATE_DOCUMENT")
            totals["thomas_private"] = len(private)
            totals["rights"] = rights
            return required, totals

        with connection.cursor() as cursor:
            exists = ledger_available(cursor)
            managed = ledger_rows(cursor, exists)
        rights_before = protected()
        existing = present_grants()
        desired, state = policy(managed)
        additions, removals = delta(desired, existing, managed)
        counts = {
            "documents": state["docs"], "users": state["users"],
            "tags": state["tags"],
            "type_gaps": sum(x[2] == type_perm.id for x in additions),
            "corr_gaps": sum(x[2] == corr_perm.id for x in additions),
            "tag_gaps": sum(x[2] == tag_perm.id for x in additions),
            "managed_revocations": len(removals),
            "thomas_private": state["thomas_private"],
        }
        if mode == "AUDIT":
            frame("INSPECTED", MODE="AUDIT", CHANGED=False,
                  LEDGER="VALID" if exists else "ABSENT",
                  MANAGED_GRANTS=len(managed),
                  **{k.upper():v for k,v in counts.items()},
                  CHILD_SEES_ELTERN_DOCUMENTS=0,
                  CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS=0,
                  DOCUMENT_ACLS_CHANGED="NO")
            return
        require(req["expected"] == counts, "EXPECTED_COUNTERS_DRIFT")
        require(len(additions) <= 2000 and len(removals) <= MAX_LEDGER,
                "WRITE_SCOPE_TOO_LARGE")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])
                # Concurrent document and ACL changes are caught by snapshot
                # checks. Protected changes to other rows cause rollback.
                if not exists:
                    require(not ledger_available(cursor),
                            "LEDGER_APPEARED_CONCURRENTLY")
                    cursor.execute(
                        "CREATE TABLE " + LEDGER + " ("
                        "subject_kind varchar(5) NOT NULL "
                        "CHECK (subject_kind IN ('user', 'group')), "
                        "subject_id bigint NOT NULL CHECK (subject_id > 0), "
                        "permission_id bigint NOT NULL CHECK (permission_id > 0), "
                        "object_pk varchar(40) NOT NULL, "
                        "PRIMARY KEY(subject_kind, subject_id, permission_id, object_pk))")
                    cursor.execute(
                        "COMMENT ON TABLE " + LEDGER + " IS %s", [COMMENT])
                require(ledger_available(cursor), "LEDGER_VERIFY_FAILED")
                require(ledger_rows(cursor, True) == managed,
                        "MANAGED_LEDGER_CONCURRENT_DRIFT")
                require(present_grants() == existing,
                        "EXPLICIT_VIEW_GRANTS_CONCURRENT_DRIFT")
                require(protected() == rights_before,
                        "NON_METADATA_SCOPE_CHANGED")
                rerequired, recheck = policy(managed)
                require(rerequired == desired and
                        recheck["rights"] == state["rights"] and
                        recheck["thomas_private"] == state["thomas_private"],
                        "DOCUMENT_LINKS_OR_ACLS_CHANGED")

                # create only the exact previously absent user/group view row
                for kind, subject, perm_id, object_pk in sorted(additions):
                    if kind == "group":
                        require(subject == fam.id and perm_id == tag_perm.id and
                                int(object_pk) in set(Tag.objects.values_list(
                                    "pk", flat=True)), "TAG_GRANT_UNEXPECTED")
                        GroupObjectPermission.objects.create(
                            group_id=subject, permission_id=perm_id,
                            content_type_id=tag_ct.id, object_pk=object_pk)
                    else:
                        require(kind == "user" and subject in
                                {u.id for u in users} and
                                perm_id in (type_perm.id, corr_perm.id),
                                "USER_METADATA_GRANT_UNEXPECTED")
                        UserObjectPermission.objects.create(
                            user_id=subject, permission_id=perm_id,
                            content_type_id=targets[perm_id][1],
                            object_pk=object_pk)
                    cursor.execute(
                        "INSERT INTO " + LEDGER +
                        " (subject_kind,subject_id,permission_id,object_pk) "
                        "VALUES (%s,%s,%s,%s)",
                        [kind,subject,perm_id,object_pk])

                # revoke only persisted exact provenance rows; never inferred
                # historical family grants or manually created user grants.
                for kind, subject, perm_id, object_pk in sorted(removals):
                    if kind == "group":
                        require(subject == fam.id and perm_id == tag_perm.id,
                                "REVOKE_TAG_SCOPE_UNREVIEWED")
                        GroupObjectPermission.objects.filter(
                            group_id=subject, permission_id=perm_id,
                            content_type_id=tag_ct.id, object_pk=object_pk).delete()
                    else:
                        require(kind == "user" and perm_id in (
                            type_perm.id,corr_perm.id), "REVOKE_USER_SCOPE_UNREVIEWED")
                        UserObjectPermission.objects.filter(
                            user_id=subject, permission_id=perm_id,
                            content_type_id=targets[perm_id][1],
                            object_pk=object_pk).delete()
                    cursor.execute(
                        "DELETE FROM " + LEDGER +
                        " WHERE subject_kind=%s AND subject_id=%s "
                        "AND permission_id=%s AND object_pk=%s",
                        [kind,subject,perm_id,object_pk])
                    require(cursor.rowcount == 1, "LEDGER_DELETE_UNVERIFIED")

                require(protected() == rights_before,
                        "PROTECTED_DATA_CHANGED")
                updated_managed = ledger_rows(cursor, True)
                require(updated_managed == (managed | additions) - removals,
                        "LEDGER_POSTCHECK_FAILED")
                updated_actual = present_grants()
                require(updated_actual == (existing | additions) - (removals & existing),
                        "VIEW_GRANT_POSTCHECK_FAILED")
                after_required, after_state = policy(updated_managed)
                require(after_state["rights"] == state["rights"] and
                        after_state["thomas_private"] == state["thomas_private"] and
                        after_state["docs"] == state["docs"],
                        "DOCUMENT_PRIVACY_POSTCHECK_FAILED")
                require(not (after_required - updated_actual),
                        "METADATA_VIEW_STILL_MISSING")

        frame("APPLIED", MODE="APPLY", CHANGED=bool(additions or removals or not exists),
              LEDGER="VALID", ADDED_TAG_GRANTS=counts["tag_gaps"],
              ADDED_TYPE_GRANTS=counts["type_gaps"],
              ADDED_CORRESPONDENT_GRANTS=counts["corr_gaps"],
              REMOVED_MANAGED_GRANTS=counts["managed_revocations"],
              MANAGED_GRANTS_AFTER=len((managed | additions) - removals),
              DOCUMENT_ACLS_CHANGED="NO", DOCUMENTS_CHANGED="NO",
              DOCUMENT_TAGS_CHANGED="NO", GLOBAL_PERMISSIONS_CHANGED="NO",
              THOMAS_PRIVATE_DENIED_TO_NADJA=state["thomas_private"],
              CHILD_SEES_ELTERN_DOCUMENTS=0,
              CHILD_SEES_THOMAS_PRIVATE_DOCUMENTS=0)
    except Refusal as e:
        frame("BLOCKED", MODE=mode, REASON=str(e), CHANGED=False)
    except Exception:
        frame("BLOCKED", MODE=mode, REASON="UNCLASSIFIED", CHANGED=False)


# Django "manage.py shell -c" does not set __name__ to "__main__".
main()
