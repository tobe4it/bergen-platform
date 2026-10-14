"""Bergen Paperless: self-service UI settings baseline for family users.

Read-only by default. Only BP_UI_SETTINGS_APPLY=1 permits Django group
permission additions. No document, account, or other settings are changed.
"""
import os
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import UiSettings

GROUP_NAMES = (
    "Eltern@bergen.intern",
    "Familie@bergen.intern",
    "Kinder@bergen.intern",
)
PERSONAL_PERMISSIONS = frozenset((
    "view_uisettings",
    "add_uisettings",
    "change_uisettings",
))
APPLY = os.environ.get("BP_UI_SETTINGS_APPLY", "0") == "1"


def verify():
    if os.environ.get("BP_UI_SETTINGS_APPLY", "0") not in ("0", "1"):
        raise RuntimeError("INVALID_APPLY_FLAG")

    ct = ContentType.objects.get_for_model(UiSettings)
    perms = {perm.codename: perm for perm in Permission.objects.filter(
        content_type=ct, codename__in=PERSONAL_PERMISSIONS
    )}
    if set(perms) != PERSONAL_PERMISSIONS:
        raise RuntimeError("UI_SETTINGS_PERMISSIONS_MISSING")

    groups = []
    for group_name in GROUP_NAMES:
        group = Group.objects.get(name=group_name)
        if group.permissions.filter(
            content_type=ct, codename="delete_uisettings"
        ).exists():
            raise RuntimeError("UNEXPECTED_UI_SETTINGS_DELETE_GRANT " + group_name)
        groups.append(group)

    group_user_ids = set()
    for group in groups:
        group_user_ids.update(group.user_set.filter(is_active=True).values_list(
            "pk", flat=True
        ))
    humans = list(User.objects.filter(pk__in=group_user_ids,
                                      is_active=True).order_by("username"))
    if any(user.username == "AnonymousUser" for user in humans):
        raise RuntimeError("ANONYMOUS_USER_IN_FAMILY_GROUP")
    candidates = [u for u in humans if not u.is_superuser]
    excluded_active = list(User.objects.filter(is_active=True)
                           .exclude(pk__in=group_user_ids)
                           .exclude(is_superuser=True)
                           .values_list("username", flat=True))
    return ct, perms, groups, candidates, excluded_active


def main():
    ct, perms, groups, candidates, excluded = verify()
    print("MODE", "APPLY" if APPLY else "DRY_RUN")
    print("ROLE_GROUPS", ", ".join(GROUP_NAMES))
    print("PERSONAL_UI_RIGHTS", ", ".join(sorted(PERSONAL_PERMISSIONS)))
    print("ELIGIBLE_USERS", ", ".join(user.username for user in candidates) or "<none>")
    print("ACTIVE_UNASSIGNED_USERS", ", ".join(sorted(excluded)) or "<none>")
    if not candidates:
        raise RuntimeError("NO_ELIGIBLE_ACTIVE_PAPERLESS_USERS")
    if not APPLY:
        print("DRY_RUN_NO_CHANGES")
        return

    with transaction.atomic():
        for group in groups:
            group.permissions.add(*(perms[name] for name in sorted(PERSONAL_PERMISSIONS)))
        for group in groups:
            actual = set(group.permissions.filter(content_type=ct).values_list(
                "codename", flat=True
            ))
            if not PERSONAL_PERMISSIONS.issubset(actual):
                raise RuntimeError("MISSING_GROUP_UI_RIGHTS " + group.name)
            if "delete_uisettings" in actual:
                raise RuntimeError("UNEXPECTED_DELETE_UI_SETTINGS " + group.name)
        for candidate in candidates:
            # Fetch a fresh user instance to avoid any cached permission set.
            current = User.objects.get(pk=candidate.pk)
            effective = current.get_all_permissions()
            for name in PERSONAL_PERMISSIONS:
                if "documents." + name not in effective:
                    raise RuntimeError("MISSING_EFFECTIVE_UI_RIGHT " +
                                       candidate.username + " " + name)
            if current.is_staff or current.is_superuser:
                raise RuntimeError("ELEVATED_ELIGIBLE_USER " + current.username)
    print("PERSONAL_UI_SETTINGS_GRANTED_AND_VERIFIED")


main()
