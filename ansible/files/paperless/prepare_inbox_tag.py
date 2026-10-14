"""Bergen Paperless tag catalogue, with explicit dry-run/commit.

Creates admin-owned tags; grants only view_tag to active regular users.
Topic tags learn from confirmed classifications; operational tags do not.
Existing user settings, document ACLs and historic documents are preserved.
"""
import copy
import os

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import MatchingModel, Tag, UiSettings
from documents.permissions import get_objects_for_user_owner_aware
from guardian.shortcuts import assign_perm, get_users_with_perms

FLAG = os.environ.get("BP_INBOX_APPLY", "0")
# name, colour, learn from training examples, inbox
CATALOGUE = (
    ("Steuer", "#5e81ac", True, False),
    ("Haus", "#a3be8c", True, False),
    ("Finanzen", "#b48ead", True, False),
    ("Versicherung", "#88c0d0", True, False),
    ("Mobilität", "#d08770", True, False),
    ("Gesundheit", "#bf616a", True, False),
    ("Bildung", "#ebcb8b", True, False),
    ("Beruf", "#81a1c1", True, False),
    ("Reise", "#8fbcbb", True, False),
    ("IT", "#5e81ac", True, False),
    ("Ehrenamt", "#a3be8c", True, False),
    ("Behörden", "#b48ead", True, False),
    ("Haustiere", "#d08770", True, False),
    ("Energie", "#ebcb8b", True, False),
    ("Gewährleistung", "#88c0d0", True, False),
    ("Posteingang", "#dfb45f", False, True),
    ("Aktion offen", "#bf616a", False, False),
    ("Frist prüfen", "#d08770", False, False),
)
SETTING_GROUP = "document_editing"
SETTING_KEY = "remove_inbox_tags"


def abort(message):
    raise RuntimeError("BERGEN_TAG_PREFLIGHT_FAILED " + message)


def inspect_existing(admin):
    names = {item[0] for item in CATALOGUE}
    if len(names) != len(CATALOGUE):
        abort("DUPLICATE_CATALOGUE_ENTRY")
    existing = {}
    for name, color, learn, inbox in CATALOGUE:
        found = list(Tag.objects.filter(name__iexact=name).select_related("owner"))
        if len(found) > 1:
            abort("DUPLICATE_TAG_NAME " + name)
        if not found:
            continue
        tag = found[0]
        if tag.name != name or tag.owner_id != admin.pk:
            abort("TAG_NOT_ADMIN_OWNED " + name)
        if tag.get_parent() is not None or tag.match:
            abort("EXISTING_TAG_HAS_PARENT_OR_MATCH " + name)
        # Only upgrade a manually created, nonmatching tag to AUTO. Do not
        # silently replace regex, literal or learned rules configured by users.
        allowed = {MatchingModel.MATCH_NONE}
        if learn:
            allowed.add(MatchingModel.MATCH_AUTO)
        if tag.matching_algorithm not in allowed:
            abort("EXISTING_TAG_HAS_CUSTOM_MATCHING " + name)
        if tag.is_inbox_tag and not inbox:
            abort("UNEXPECTED_INBOX_TAG " + name)
        for user, perms in get_users_with_perms(tag, attach_perms=True).items():
            if set(perms) != {"view_tag"}:
                abort("UNEXPECTED_TAG_USER_ACL " + name + " " + user.username)
        existing[name] = tag
    unrelated_inboxes = list(
        Tag.objects.filter(is_inbox_tag=True).exclude(
            pk__in=[tag.pk for tag in existing.values()]
        ).values_list("name", flat=True)
    )
    if unrelated_inboxes:
        abort("OTHER_INBOX_TAGS_NEED_REVIEW " + repr(unrelated_inboxes))
    return existing


def inspect_preferences(users):
    result = []
    for user in users:
        try:
            row = UiSettings.objects.get(user=user)
            data = row.settings or {}
        except UiSettings.DoesNotExist:
            data = {}
        if not isinstance(data, dict):
            abort("INVALID_UI_SETTINGS " + user.username)
        section = data.get(SETTING_GROUP, {})
        if not isinstance(section, dict):
            abort("INVALID_DOCUMENT_EDITING_SETTINGS " + user.username)
        current = section.get(SETTING_KEY)
        if current is not None and current not in (True, False, "true", "false"):
            abort("INVALID_REMOVE_INBOX_SETTING " + user.username)
        result.append((user, data, current))
    return result


def main():
    if FLAG not in ("0", "1"):
        abort("INVALID_APPLY_FLAG")
    admin = User.objects.get(username="admin")
    if not admin.is_active or not admin.is_superuser:
        abort("EXPECTED_ADMIN_MISSING")
    users = list(User.objects.filter(is_active=True).exclude(
        username__iexact="AnonymousUser"
    ).order_by("username"))
    if not users:
        abort("NO_ACTIVE_USERS")
    # A real legacy user named AnonymousUser is deliberately excluded.
    eligible = [user for user in users if not user.is_superuser]
    view_perm = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(Tag), codename="view_tag"
    )
    existing = inspect_existing(admin)
    preferences = inspect_preferences(users)
    print("MODE", "APPLY" if FLAG == "1" else "DRY_RUN")
    for name, _color, learn, inbox in CATALOGUE:
        current = existing.get(name)
        print("TAG_PLAN", name,
              "EXISTS" if current else "CREATE",
              "AUTO" if learn else "NONE",
              "INBOX" if inbox else "NORMAL")
    print("TAG_READERS", ",".join(u.username for u in eligible))
    print("REMOVE_INBOX_ON_SAVE", ",".join(
        u.username + ":" + ("DEFAULT_TRUE" if current is None else "KEEP_" + str(current))
        for u, _data, current in preferences
    ))
    print("DOCUMENTS_AND_ACLS_UNCHANGED")
    print("FUTURE_USERS_REQUIRE_BASELINE_PROVISIONING")
    if FLAG == "0":
        print("DRY_RUN_NO_CHANGES")
        return

    created = 0
    updated = 0
    defaulted = 0
    with transaction.atomic():
        for name, color, learn, inbox in CATALOGUE:
            target_algorithm = (
                MatchingModel.MATCH_AUTO if learn else MatchingModel.MATCH_NONE
            )
            tag = existing.get(name)
            if tag is None:
                tag = Tag.objects.create(
                    name=name, owner=admin, color=color, match="",
                    matching_algorithm=target_algorithm, is_inbox_tag=inbox
                )
                created += 1
            else:
                fields = []
                if tag.matching_algorithm != target_algorithm:
                    tag.matching_algorithm = target_algorithm
                    fields.append("matching_algorithm")
                if tag.is_inbox_tag != inbox:
                    tag.is_inbox_tag = inbox
                    fields.append("is_inbox_tag")
                if fields:
                    tag.save(update_fields=fields)
                    updated += 1
            for user in eligible:
                # Existing global model right is left unchanged. This grants
                # only the ability to view the catalogue and its entries.
                if not user.has_perm("documents.view_tag"):
                    user.user_permissions.add(view_perm)
                assign_perm("view_tag", user, tag)

        for user, data, current in preferences:
            if current is not None:
                continue
            new_data = copy.deepcopy(data)
            new_data.setdefault(SETTING_GROUP, {})[SETTING_KEY] = True
            UiSettings.objects.update_or_create(
                user=user, defaults={"settings": new_data}
            )
            defaulted += 1

        for name, _color, learn, inbox in CATALOGUE:
            tag = Tag.objects.get(name=name, owner=admin)
            if tag.matching_algorithm != (
                MatchingModel.MATCH_AUTO if learn else MatchingModel.MATCH_NONE
            ) or tag.is_inbox_tag != inbox or tag.get_parent() is not None:
                abort("POST_TAG_POLICY " + name)
            for user in eligible:
                fresh = User.objects.get(pk=user.pk)
                if not fresh.has_perm("documents.view_tag"):
                    abort("MISSING_TAG_MODEL_READ " + user.username)
                if not get_objects_for_user_owner_aware(
                    fresh, "documents.view_tag", Tag
                ).filter(pk=tag.pk).exists():
                    abort("MISSING_TAG_OBJECT_READ " + name + "/" + user.username)
        for user, _data, _current in preferences:
            setting = UiSettings.objects.get(user=user).settings
            if setting[SETTING_GROUP][SETTING_KEY] not in (
                True, False, "true", "false"
            ):
                abort("POST_USER_SETTING " + user.username)
    print("BERGEN_TAG_CATALOGUE_COMMITTED_AND_VERIFIED",
          "created=" + str(created),
          "updated=" + str(updated),
          "preferences_defaulted=" + str(defaulted))


main()
