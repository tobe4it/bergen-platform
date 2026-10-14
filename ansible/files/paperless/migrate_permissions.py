"""Controlled Paperless-ngx ACL migration via Django manage.py shell -c.

Default is read-only. BP_PERMISSIONS_COMMIT=1 is required for mutation.
No document contents or owners are changed. No delete-object grants are added.
"""
import os
from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from documents.models import Document, Workflow
from documents.permissions import permitted_document_ids
from guardian.shortcuts import assign_perm, get_groups_with_perms, get_users_with_perms

COMMIT = os.environ.get("BP_PERMISSIONS_COMMIT", "0") == "1"
PARENTS = ("nadja", "thomas")
ELTERN = "Eltern@bergen.intern"
FAMILIE = "Familie@bergen.intern"
WORKFLOWS = {
    1: ("Bergen Ingest | 00 Admin-Auffang", 0, "/usr/src/paperless/consume/*", "admin"),
    2: ("Bergen Ingest | 10 Privat thomas", 10, "/usr/src/paperless/consume/Privat/thomas/*", "thomas"),
    3: ("Bergen Ingest | 20 Privat nadja", 20, "/usr/src/paperless/consume/Privat/nadja/*", "nadja"),
    4: ("Bergen Ingest | 30 Eltern", 30, "/usr/src/paperless/consume/Eltern/*", "admin"),
    5: ("Bergen Ingest | 40 Familie", 40, "/usr/src/paperless/consume/Familie/*", "admin"),
}
ADULT_GLOBAL = {
    "add_document", "change_document", "view_document",
    "add_tag", "change_tag", "view_tag",
    "add_correspondent", "change_correspondent", "view_correspondent",
    "add_documenttype", "change_documenttype", "view_documenttype",
}


def fail(message):
    raise RuntimeError("PAPERLESS_ACL_PRECHECK_FAILED " + message)


def names(manager):
    return set(manager.values_list("username", flat=True))


def object_permissions(document):
    groups = {g.name: set(p) for g, p in get_groups_with_perms(document, attach_perms=True).items()}
    users = {u.username: set(p) for u, p in get_users_with_perms(document, attach_perms=True).items()}
    return groups, users


def verify_workflow(workflow_id, expected):
    name, priority, path, owner = expected
    try:
        workflow = Workflow.objects.get(pk=workflow_id)
    except Workflow.DoesNotExist:
        fail("MISSING_WORKFLOW " + str(workflow_id))
    if (workflow.name != name or not workflow.enabled or workflow.order != priority or
            workflow.triggers.count() != 1 or workflow.actions.count() != 1):
        fail("UNEXPECTED_WORKFLOW " + str(workflow_id))
    trigger = workflow.triggers.get()
    action = workflow.actions.get()
    if (trigger.type != 1 or trigger.filter_path != path or
            str(trigger.sources) not in ("['1']", "1") or action.type != 1 or
            not action.assign_owner or action.assign_owner.username != owner or
            action.remove_all_permissions or action.remove_all_owners):
        fail("UNEXPECTED_WORKFLOW_ROUTING " + str(workflow_id))
    actual_view_groups = set(action.assign_view_groups.values_list("name", flat=True))
    actual_change_groups = set(action.assign_change_groups.values_list("name", flat=True))
    actual_view_users = names(action.assign_view_users)
    actual_change_users = names(action.assign_change_users)
    expected_view_groups = {ELTERN} if workflow_id == 4 else ({FAMILIE} if workflow_id == 5 else set())
    expected_change_groups = {ELTERN} if workflow_id == 4 else set()
    expected_parents = set(PARENTS) if workflow_id in (4, 5) else set()
    if actual_view_groups != expected_view_groups:
        fail("WRONG_WORKFLOW_VIEW_GROUPS " + name)
    if actual_change_groups not in (set(), expected_change_groups):
        fail("WRONG_WORKFLOW_CHANGE_GROUPS " + name)
    if actual_view_users not in (set(), expected_parents):
        fail("WRONG_WORKFLOW_VIEW_USERS " + name)
    if actual_change_users not in (set(), expected_parents if workflow_id in (4, 5) else set()):
        fail("WRONG_WORKFLOW_CHANGE_USERS " + name)
    return action


def collect_documents(admin):
    """Select only admin-owned docs with exactly one known shared group."""
    found = []
    for doc in Document.objects.filter(owner=admin).order_by("pk"):
        object_groups, object_users = object_permissions(doc)
        if not (set(object_groups) & {ELTERN, FAMILIE}):
            continue
        if set(object_groups) not in ({ELTERN}, {FAMILIE}):
            fail("UNEXPECTED_GROUP_ON_SHARED_DOC " + str(doc.pk))
        group_name = next(iter(object_groups))
        allowed_group_perms = ({"view_document"}, {"view_document", "change_document"}) if group_name == ELTERN else ({"view_document"},)
        if object_groups[group_name] not in allowed_group_perms:
            fail("UNEXPECTED_GROUP_PERMISSION_ON_DOC " + str(doc.pk))
        if not set(object_users).issubset(set(PARENTS)):
            fail("UNEXPECTED_DIRECT_USER_ON_DOC " + str(doc.pk))
        for username, perms in object_users.items():
            allowed = ({"view_document"}, {"view_document", "change_document"})
            if perms not in allowed:
                fail("UNEXPECTED_USER_PERMISSION_ON_DOC %s/%s" % (doc.pk, username))
        found.append((doc, group_name))
    if not any(group == ELTERN for _, group in found) or not any(group == FAMILIE for _, group in found):
        fail("MISSING_EXPECTED_SHARED_DOCS")
    return found


def assert_final(document, group_name):
    expected_groups = ({ELTERN: {"view_document", "change_document"}} if group_name == ELTERN
                       else {FAMILIE: {"view_document"}})
    object_groups, object_users = object_permissions(document)
    if object_groups != expected_groups:
        fail("POST_GROUP_PERMS %s %s" % (document.pk, repr(object_groups)))
    expected_users = {name: {"view_document", "change_document"} for name in PARENTS}
    if object_users != expected_users:
        fail("POST_USER_PERMS %s %s" % (document.pk, repr(object_users)))
    for user in User.objects.filter(is_active=True):
        expected_view = user.is_superuser or user.pk == document.owner_id or user.groups.filter(name=group_name).exists()
        expected_change = (user.is_superuser or user.pk == document.owner_id or
                           (user.groups.filter(name=ELTERN).exists() if group_name == ELTERN else user.username in PARENTS))
        expected_delete = user.is_superuser or user.pk == document.owner_id
        for perm, expected in (("view_document", expected_view),
                               ("change_document", expected_change),
                               ("delete_document", expected_delete)):
            effective = permitted_document_ids(user, perm=perm).filter(pk=document.pk).exists()
            if effective != expected:
                fail("POST_EFFECTIVE_PERMISSION doc=%s user=%s perm=%s actual=%s expected=%s" %
                     (document.pk, user.username, perm, effective, expected))
            if expected and not user.has_perm("documents." + perm):
                fail("MISSING_MODEL_PERMISSION doc=%s user=%s perm=%s" % (document.pk, user.username, perm))



def audit_private_documents(users, after=False):
    """Require private documents of both parents remain isolated."""
    count = 0
    population = list(User.objects.filter(is_active=True).order_by("pk"))
    for username in PARENTS:
        owner = users[username]
        for document in Document.objects.filter(owner=owner).order_by("pk"):
            count += 1
            object_groups, object_users = object_permissions(document)
            if object_groups or object_users:
                fail("UNEXPECTED_PRIVATE_GRANT %s owner=%s" % (document.pk, username))
            if not after:
                continue
            for actor in population:
                expected = actor.is_superuser or actor.pk == owner.pk
                for permission in ("view_document", "change_document", "delete_document"):
                    actual = permitted_document_ids(actor, perm=permission).filter(
                        pk=document.pk
                    ).exists()
                    if actual != expected:
                        fail("PRIVATE_ACCESS_DIFFERENCE doc=%s actor=%s perm=%s" % (
                            document.pk, actor.username, permission
                        ))
                    if expected and not actor.has_perm("documents." + permission):
                        fail("PRIVATE_GLOBAL_PERMISSION_MISSING doc=%s actor=%s perm=%s" % (
                            document.pk, actor.username, permission
                        ))
    print("PRIVATE_DOCUMENTS_AUDITED", count, "after_commit=", after)



def main():
    if os.environ.get("BP_PERMISSIONS_COMMIT") not in (None, "0", "1"):
        fail("INVALID_COMMIT_FLAG")
    if Workflow.objects.count() != len(WORKFLOWS):
        fail("UNEXPECTED_WORKFLOW_COUNT")
    # In this Paperless version, unowned documents can be visible to any
    # active user for some object-level actions. Do not grant delete model
    # permission to normal accounts until ownership is complete.
    if Document.objects.filter(owner__isnull=True).exists():
        fail("UNOWNED_DOCUMENTS_BLOCK_MODEL_DELETE_PERMISSION")
    users = {name: User.objects.get(username=name) for name in ("admin",) + PARENTS}
    if any(not user.is_active for user in users.values()):
        fail("INACTIVE_REQUIRED_USER")
    if not users["admin"].is_superuser or any(users[name].is_superuser or users[name].is_staff for name in PARENTS):
        fail("UNEXPECTED_ADMIN_ROLE")
    groups = {name: Group.objects.get(name=name) for name in (ELTERN, FAMILIE)}
    adult_members = set(groups[ELTERN].user_set.filter(is_active=True).values_list("username", flat=True))
    if adult_members != set(PARENTS):
        fail("UNEXPECTED_ELTERN_GROUP_MEMBERS " + repr(adult_members))
    if not set(PARENTS).issubset(set(groups[FAMILIE].user_set.filter(is_active=True).values_list("username", flat=True))):
        fail("PARENTS_NOT_IN_FAMILY")
    for name, group in groups.items():
        if group.permissions.filter(codename="delete_document", content_type__app_label="documents").exists():
            fail("SHARED_GROUP_HAS_GLOBAL_DELETE " + name)
    actions = {number: verify_workflow(number, expected) for number, expected in WORKFLOWS.items()}
    documents = collect_documents(users["admin"])
    audit_private_documents(users, after=False)
    permissions = {
        codename: Permission.objects.get(content_type__app_label="documents", codename=codename)
        for codename in ADULT_GLOBAL | {"delete_document"}
    }
    print("MODE", "COMMIT" if COMMIT else "DRY_RUN", "WORKFLOWS", len(actions), "SHARED_DOCUMENTS", len(documents))
    for document, group in documents:
        print("CANDIDATE", document.pk, "scope=", "Eltern" if group == ELTERN else "Familie", "owner=admin")
    print("TARGET_GROUP_ELTERN_MODEL", ",".join(sorted(ADULT_GLOBAL)))
    print("TARGET_PERSONAL_DELETE_MODEL", ",".join(PARENTS))
    if not COMMIT:
        print("DRY_RUN_NO_CHANGES")
        return

    with transaction.atomic():
        groups[ELTERN].permissions.add(*(permissions[name] for name in sorted(ADULT_GLOBAL)))
        for name in PARENTS:
            users[name].user_permissions.add(permissions["delete_document"])
        actions[4].assign_change_groups.add(groups[ELTERN])
        actions[4].assign_view_users.add(*(users[name] for name in PARENTS))
        actions[4].assign_change_users.add(*(users[name] for name in PARENTS))
        actions[5].assign_view_users.add(*(users[name] for name in PARENTS))
        actions[5].assign_change_users.add(*(users[name] for name in PARENTS))
        for doc, group_name in documents:
            if group_name == ELTERN:
                assign_perm("change_document", groups[ELTERN], doc)
                for name in PARENTS:
                    assign_perm("view_document", users[name], doc)
                    assign_perm("change_document", users[name], doc)
            else:
                for name in PARENTS:
                    assign_perm("view_document", users[name], doc)
                    assign_perm("change_document", users[name], doc)
        for doc, group in documents:
            assert_final(doc, group)
        audit_private_documents(users, after=True)
        for number, expected in WORKFLOWS.items():
            verify_workflow(number, expected)
    print("PAPERLESS_ACL_MIGRATION_COMMITTED_AND_VERIFIED")


main()
