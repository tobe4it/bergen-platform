"""Bergen Paperless 3.3: audit end-user permissions; enable own-tag deletion.

Default: read-only. Set BP_USER_RIGHTS_APPLY=1 to grant ONLY delete_tag
to active non-staff accounts. No object ACLs, documents, or metadata changed.

PaperlessObjectPermissions checks both model delete_tag and owner/object
permission. A tag without an owner bypasses object checks, so such tags
must be resolved before granting global delete_tag.
"""
import os

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import Tag
from guardian.shortcuts import get_groups_with_perms, get_users_with_perms

FLAG = os.environ.get("BP_USER_RIGHTS_APPLY", "0")
TARGET_RIGHT = "documents.delete_tag"
# App label, model, permissions: audit only; no automatic grants.
# The audit enumerates the real Permission rows from the live Paperless DB.
# This avoids assuming app labels for optional plugins or newly added models.
# Conservative recommendations, not granted by this migration.
REVIEW_ONLY = (
    "documents.add_savedview", "documents.view_savedview",
    "documents.change_savedview", "documents.delete_savedview",
    "documents.add_note", "documents.view_note",
    "documents.change_note", "documents.delete_note",
    "documents.view_customfield", "documents.view_storagepath",
    "documents.view_paperlesstask",
)


def fail(message):
    raise RuntimeError("BERGEN_USER_RIGHTS_PRECHECK_FAILED " + message)


def regular_users():
    users = list(
        User.objects.filter(is_active=True, is_staff=False, is_superuser=False)
        .exclude(username__iexact="AnonymousUser").order_by("username")
    )
    if not users:
        fail("NO_ACTIVE_REGULAR_USERS")
    return users


def tag_delete_blockers():
    blockers = []
    unowned = list(Tag.objects.filter(owner__isnull=True).values_list("pk", flat=True))
    if unowned:
        blockers.append("UNOWNED_TAG_IDS=" + ",".join(str(pk) for pk in unowned))
    for tag in Tag.objects.select_related("owner").order_by("pk"):
        for group, rights in get_groups_with_perms(tag, attach_perms=True).items():
            if "delete_tag" in rights:
                blockers.append("GROUP_DELETE_OBJECT tag=%d group=%s" % (tag.pk, group.name))
        for user, rights in get_users_with_perms(tag, attach_perms=True).items():
            if "delete_tag" in rights and user.pk != tag.owner_id:
                blockers.append("FOREIGN_DELETE_OBJECT tag=%d user=%s" % (tag.pk, user.username))
    return blockers


def audit_user(user):
    effective = user.get_all_permissions()
    print("USER", user.username, "STAFF", user.is_staff, "SUPERUSER", user.is_superuser)
    for content_type in ContentType.objects.filter(
        permission__isnull=False
    ).distinct().order_by("app_label", "model"):
        perms = Permission.objects.filter(content_type=content_type).order_by("codename")
        rights = [p.codename for p in perms if
                  content_type.app_label + "." + p.codename in effective]
        print("RIGHTS", user.username,
              content_type.app_label + "." + content_type.model,
              ",".join(rights) if rights else "-")
    missing = [right for right in REVIEW_ONLY if right not in effective]
    print("REVIEW_ONLY_MISSING", user.username, ",".join(missing) if missing else "-")
    print("DELETE_TAG", user.username,
          "PRESENT" if TARGET_RIGHT in effective else "MISSING")


def main():
    if FLAG not in ("0", "1"):
        fail("INVALID_APPLY_FLAG")
    users = regular_users()
    perm = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(Tag),
        codename="delete_tag",
    )
    if perm.content_type.app_label != "documents":
        fail("WRONG_PERMISSION_CONTENT_TYPE")
    blockers = tag_delete_blockers()
    print("MODE", "APPLY" if FLAG == "1" else "DRY_RUN")
    print("REGULAR_USERS", ",".join(user.username for user in users))
    print("TARGET", TARGET_RIGHT, "MODEL_ONLY")
    print("OBJECT_ACLS_AND_DOCUMENTS_UNCHANGED")
    for blocker in blockers:
        print("BLOCKER", blocker)
    for user in users:
        audit_user(user)
    print("FUTURE_USERS_REQUIRE_BASELINE_PROVISIONING")
    if FLAG == "0":
        print("DRY_RUN_NO_CHANGES")
        return
    if blockers:
        fail("TAG_DELETE_UNSAFE " + "; ".join(blockers))
    changed = 0
    with transaction.atomic():
        # Recheck inside transaction; never grant if the tag catalogue is
        # unsafe for a model-level delete permission.
        if tag_delete_blockers():
            fail("TAG_DELETE_PRECONDITIONS_CHANGED")
        for user in users:
            if not user.has_perm(TARGET_RIGHT):
                user.user_permissions.add(perm)
                changed += 1
        for user in users:
            fresh = User.objects.get(pk=user.pk)
            if not fresh.has_perm(TARGET_RIGHT):
                fail("MISSING_DELETE_TAG " + fresh.username)
            if fresh.is_staff or fresh.is_superuser:
                fail("ELEVATED_REGULAR_USER " + fresh.username)
        if tag_delete_blockers():
            fail("TAG_DELETE_POSTCONDITIONS_CHANGED")
    print("OWN_TAG_DELETE_COMMITTED_AND_VERIFIED", "new_model_grants=" + str(changed))


main()
