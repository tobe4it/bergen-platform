"""Provision Bergen Paperless inbox tag and per-user review defaults.

Run through Paperless Django manage.py shell -c. Dry-run unless
BP_INBOX_APPLY=1. Existing custom remove-on-save choices remain unchanged.
Does not tag historic documents, alter document ACLs, or delete anything.
"""
import copy
import os

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import MatchingModel, Tag, UiSettings
from documents.permissions import get_objects_for_user_owner_aware
from guardian.shortcuts import assign_perm, get_groups_with_perms, get_users_with_perms

FLAG = os.environ.get("BP_INBOX_APPLY", "0")
NAME = "Posteingang"
COLOR = "#dfb45f"
GROUP_NAMES = ("Eltern@bergen.intern", "Familie@bergen.intern", "Kinder@bergen.intern")
SETTING_GROUP = "document_editing"
SETTING_KEY = "remove_inbox_tags"


def abort(reason):
    raise RuntimeError("BERGEN_INBOX_PREFLIGHT_FAILED: " + reason)


def inspect_tag(admin):
    matches = list(Tag.objects.filter(name__iexact=NAME).select_related("owner"))
    if len(matches) > 1:
        abort("DUPLICATE_INBOX_TAG_NAME")
    tag = matches[0] if matches else None
    if tag is not None:
        if tag.name != NAME or tag.owner_id != admin.pk:
            abort("INBOX_NAME_ALREADY_OWNED_BY_OTHER_ACCOUNT")
        if (
            not tag.is_inbox_tag or tag.matching_algorithm != MatchingModel.MATCH_NONE
            or tag.match or tag.get_parent() is not None
        ):
            abort("INBOX_TAG_HAS_UNEXPECTED_PROPERTIES")
        if tag.color != COLOR:
            print("NOTICE_EXISTING_INBOX_COLOR_RETAINED", tag.color)
        # Never silently adopt a tag with an unexpected object-policy history.
        for group, rights in get_groups_with_perms(tag, attach_perms=True).items():
            if set(rights) != {"view_tag"} or group.name not in GROUP_NAMES:
                abort("UNEXPECTED_INBOX_GROUP_ACL_" + group.name)
        for user, rights in get_users_with_perms(tag, attach_perms=True).items():
            if set(rights) != {"view_tag"} or not user.is_active:
                abort("UNEXPECTED_INBOX_USER_ACL_" + user.username)
    others = list(Tag.objects.filter(is_inbox_tag=True).exclude(pk=tag.pk if tag else None)
                  .values_list("pk", "name"))
    if others:
        abort("OTHER_INBOX_TAGS_REQUIRE_REVIEW: " + repr(others))
    return tag


def inspect_preferences(accounts):
    planned = []
    for user in accounts:
        try:
            current = UiSettings.objects.get(user=user)
            data = current.settings
        except UiSettings.DoesNotExist:
            data = None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            abort("INVALID_UI_SETTINGS_TYPE_" + user.username)
        subgroup = data.get(SETTING_GROUP, {})
        if not isinstance(subgroup, dict):
            abort("INVALID_DOCUMENT_EDITING_SETTINGS_" + user.username)
        old = subgroup.get(SETTING_KEY)
        if old is not None and not isinstance(old, (bool, str)):
            abort("INVALID_REVIEW_SETTING_TYPE_" + user.username)
        if isinstance(old, str) and old not in ("true", "false"):
            abort("INVALID_REVIEW_SETTING_VALUE_" + user.username)
        planned.append((user, data, old))
    return planned


def verify_tag(tag, admin, accounts, groups, eligible_users):
    tag.refresh_from_db()
    if not tag.is_inbox_tag or tag.owner_id != admin.pk:
        abort("INBOX_TAG_IDENTITY_CHANGED")
    if tag.matching_algorithm != MatchingModel.MATCH_NONE or tag.get_parent() is not None:
        abort("INBOX_TAG_MATCHING_POLICY_CHANGED")
    for group in groups:
        gp = get_groups_with_perms(tag, attach_perms=True)
        if set(gp.get(group, [])) != {"view_tag"}:
            abort("MISSING_GROUP_TAG_READ_" + group.name)
        if not group.permissions.filter(
            codename="view_tag", content_type__app_label="documents"
        ).exists():
            abort("MISSING_GROUP_GLOBAL_TAG_VIEW_" + group.name)
    for user in eligible_users:
        if not user.has_perm("documents.view_tag"):
            abort("MISSING_GLOBAL_VIEW_TAG_" + user.username)
        if not get_objects_for_user_owner_aware(user, "documents.view_tag", Tag).filter(
            pk=tag.pk
        ).exists():
            abort("MISSING_INBOX_TAG_VISIBILITY_" + user.username)
    for user in accounts:
        setting = UiSettings.objects.get(user=user)
        value = setting.settings[SETTING_GROUP][SETTING_KEY]
        if value not in (True, False, "true", "false"):
            abort("INVALID_SAVED_REVIEW_PREFERENCE_" + user.username)
    for group, rights in get_groups_with_perms(tag, attach_perms=True).items():
        if set(rights) != {"view_tag"}:
            abort("INBOX_GROUP_ACL_ESCALATED_" + group.name)
    for user, rights in get_users_with_perms(tag, attach_perms=True).items():
        if set(rights) != {"view_tag"}:
            abort("INBOX_USER_ACL_ESCALATED_" + user.username)


def main():
    if FLAG not in ("0", "1"):
        abort("INVALID_APPLY_FLAG")
    admin = User.objects.get(username="admin")
    if not admin.is_active or not admin.is_superuser:
        abort("EXPECTED_ADMIN_SUPERUSER_NOT_FOUND")
    groups = [Group.objects.get(name=name) for name in GROUP_NAMES]
    accounts = list(User.objects.filter(is_active=True).exclude(
        username__iexact="AnonymousUser"
    ).order_by("username"))
    if not accounts:
        abort("NO_REGULAR_USERS")
    eligible = [user for user in accounts if user.has_perm("documents.view_document")]
    tag_perm = Permission.objects.get(content_type=ContentType.objects.get_for_model(Tag),
                                      codename="view_tag")
    existing = inspect_tag(admin)
    preferences = inspect_preferences(accounts)
    print("MODE", "APPLY" if FLAG == "1" else "DRY_RUN")
    print("INBOX_TAG", NAME, "EXISTS" if existing else "CREATE_ADMIN_OWNED")
    print("TAG_ACCESS_GROUPS", ",".join(GROUP_NAMES))
    print("DOC_VIEW_USERS", ",".join(user.username for user in eligible))
    print("USER_PREFERENCES", ",".join(
        "%s:%s" % (user.username, "DEFAULT_TRUE" if value is None else "KEEP_" + str(value))
        for user, _data, value in preferences
    ))
    print("HISTORIC_DOCUMENTS_UNTOUCHED")
    print("FUTURE_USER_ONBOARDING_REQUIRES_RERUN")
    if FLAG == "0":
        print("DRY_RUN_NO_CHANGES")
        return

    created = 0
    changed_preferences = 0
    with transaction.atomic():
        tag = existing
        if tag is None:
            tag = Tag.objects.create(
                name=NAME, owner=admin, color=COLOR, is_inbox_tag=True,
                match="", matching_algorithm=MatchingModel.MATCH_NONE,
            )
            created = 1
        for group in groups:
            group.permissions.add(tag_perm)
            assign_perm("view_tag", group, tag)
        for user in eligible:
            user.user_permissions.add(tag_perm)
            assign_perm("view_tag", user, tag)
        for user, original, old in preferences:
            if old is not None:
                continue
            data = copy.deepcopy(original)
            data.setdefault(SETTING_GROUP, {})[SETTING_KEY] = True
            UiSettings.objects.update_or_create(user=user,
                                                 defaults={"settings": data})
            changed_preferences += 1
        # Query fresh User objects, so Django's permission cache cannot hide errors.
        eligible = list(User.objects.filter(pk__in=[u.pk for u in eligible]).order_by("pk"))
        verify_tag(tag, admin, accounts, groups, eligible)
    print("INBOX_TAG_PROVISIONED_AND_VERIFIED", "created=" + str(created),
          "settings_defaulted=" + str(changed_preferences))


main()
