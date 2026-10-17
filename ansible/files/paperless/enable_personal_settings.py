"""Bergen Paperless: grant *personal* UI settings to all active users.

Default dry-run. BP_UI_SETTINGS_APPLY=1 is required to assign permissions.
Does not grant access to any other user's settings or documents.
The existing admin superuser already possesses these rights.
"""
import os
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from documents.models import UiSettings

RIGHTS = frozenset(("add_uisettings", "view_uisettings", "change_uisettings"))


def inspect():
    flag = os.environ.get("BP_UI_SETTINGS_APPLY", "0")
    if flag not in ("0", "1"):
        raise RuntimeError("INVALID_APPLY_FLAG")
    content_type = ContentType.objects.get_for_model(UiSettings)
    perms = {
        perm.codename: perm for perm in Permission.objects.filter(
            content_type=content_type, codename__in=RIGHTS
        )
    }
    if set(perms) != RIGHTS:
        raise RuntimeError("REQUIRED_UI_SETTINGS_PERMISSIONS_NOT_FOUND")

    # A historic real account named AnonymousUser exists in this instance.
    # Never grant rights to it. Admin is a superuser and needs no new grants.
    candidates = list(
        User.objects.filter(is_active=True, is_superuser=False)
        .exclude(username__iexact="AnonymousUser")
        .order_by("username")
    )
    if not candidates:
        raise RuntimeError("NO_ACTIVE_USER_CANDIDATES")
    if any(user.username == "AnonymousUser" or user.is_staff for user in candidates):
        raise RuntimeError("UNEXPECTED_TARGET_ACCOUNT")

    excluded = list(
        User.objects.filter(is_active=True)
        .exclude(pk__in=[u.pk for u in candidates])
        .order_by("username").values_list("username", flat=True)
    )
    return flag == "1", perms, candidates, excluded


def main():
    apply, perms, candidates, excluded = inspect()
    print("MODE", "APPLY" if apply else "DRY_RUN")
    print("PERSONAL_UI_RIGHTS", ",".join(sorted(RIGHTS)))
    print("ELIGIBLE_USERS", ",".join(u.username for u in candidates))
    print("EXCLUDED_ACTIVE", ",".join(excluded))
    print("FUTURE_USERS_REQUIRE_BASELINE_PROVISIONING")
    if not apply:
        print("DRY_RUN_NO_CHANGES")
        return

    with transaction.atomic():
        for candidate in candidates:
            candidate.user_permissions.add(*(perms[key] for key in sorted(RIGHTS)))
        for candidate in candidates:
            fresh = User.objects.get(pk=candidate.pk)
            effective = fresh.get_all_permissions()
            for codename in RIGHTS:
                if "documents." + codename not in effective:
                    raise RuntimeError(
                        "MISSING_UI_SETTINGS_PERMISSION %s %s"
                        % (fresh.username, codename)
                    )
            if fresh.is_staff or fresh.is_superuser:
                raise RuntimeError("ELEVATED_USER " + fresh.username)
    print("PERSONAL_UI_SETTINGS_COMMITTED_AND_VERIFIED")


main()
