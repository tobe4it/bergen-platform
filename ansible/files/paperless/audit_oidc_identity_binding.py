"""Paperless allauth OIDC subjects: read-only in-process Django inventory.

Run through manage.py shell -c in the existing Paperless container.
Input: one-use secret challenge and provider only through stdin.
Never outputs raw personal fields, tokens, or document content.
"""
import hashlib
import hmac
import json
import sys

from django.contrib.auth.models import User
from django.conf import settings
from allauth.socialaccount.models import SocialAccount


# A uniquely framed single-line result tolerates django-admin shell banners
# without printing private account details into controller debug output.
RESULT_FRAME = "BERGEN_PAPERLESS_OIDC_AUDIT_V1:"


class Unsafe(Exception):
    pass


# Allauth OpenID Connect is a multi-provider facade. Its SocialAccount.provider
# equals the configured provider_id, not necessarily "openid_connect".
PROVIDER_FAILURE_CODES = frozenset({
    "OIDC_CONFIG_MISSING", "OIDC_CONFIG_AMBIGUOUS",
    "OIDC_CONFIG_INVALID", "OIDC_SELECTOR_INVALID",
})


def selected_oidc_provider(providers, requested):
    # Never enumerate arbitrary SocialAccount.provider values or select an
    # unknown identity provider merely because it has a matching email/sub.
    if not isinstance(providers, dict):
        raise Unsafe("OIDC_CONFIG_MISSING")
    oidc = providers.get("openid_connect")
    if not isinstance(oidc, dict):
        raise Unsafe("OIDC_CONFIG_MISSING")
    apps = oidc.get("APPS")
    if not isinstance(apps, list) or not 1 <= len(apps) <= 10:
        raise Unsafe("OIDC_CONFIG_MISSING")
    ids = []
    for app in apps:
        if not isinstance(app, dict):
            raise Unsafe("OIDC_CONFIG_INVALID")
        # An explicitly configured app without provider_id uses the allauth
        # provider type as a legacy fallback; never infer from user rows.
        provider_id = app.get("provider_id") or "openid_connect"
        if (not isinstance(provider_id, str)
            or not 1 <= len(provider_id) <= 200
            or not all(c.isascii() and (c.isalnum() or c in "._:-")
                       for c in provider_id)):
            raise Unsafe("OIDC_CONFIG_INVALID")
        ids.append(provider_id)
    if len(ids) != len(set(ids)):
        raise Unsafe("OIDC_CONFIG_AMBIGUOUS")
    if requested == "auto":
        if len(ids) != 1:
            raise Unsafe("OIDC_CONFIG_AMBIGUOUS")
        return ids[0]
    if not isinstance(requested, str) or requested not in ids:
        raise Unsafe("OIDC_SELECTOR_INVALID")
    return requested


def seal(key, item):
    if not isinstance(item, str) or not item or len(item) > 1024:
        raise Unsafe("Invalid identity field")
    return hmac.new(key.encode(), item.encode(), hashlib.sha256).hexdigest()


def read_rows(key, provider):
    if not isinstance(provider, str) or not provider or len(provider) > 80:
        raise Unsafe("Unknown allauth provider mapping")
    accounts = list(
        SocialAccount.objects.filter(provider=provider)
        .select_related("user").order_by("id")[:1001]
    )
    if len(accounts) > 1000:
        raise Unsafe("Too many social accounts")
    out = []
    seen = set()
    for account in accounts:
        user = account.user
        if not isinstance(user, User):
            raise Unsafe("Bad user model")
        email = user.email.strip().casefold() if isinstance(user.email, str) else ""
        if not email or len(email) > 320 or email in seen:
            raise Unsafe("Duplicate or missing email")
        seen.add(email)
        data = account.extra_data or {}
        if not isinstance(data, dict):
            raise Unsafe("Bad OIDC data")
        # Verified uid and stored ID-token sub are distinct candidates.
        # A matching subject does not prove issuer or Paperless permissions.
        uid = account.uid if isinstance(account.uid, str) and account.uid else None
        sub = data.get("sub") if isinstance(data.get("sub"), str) else None
        if not uid and not sub:
            raise Unsafe("OIDC subject missing")
        out.append({
            "email": seal(key, email),
            "uid": seal(key, uid) if uid else None,
            "sub": seal(key, sub) if sub else None,
            "active": bool(user.is_active),
            "staff": bool(user.is_staff or user.is_superuser),
        })
    return sorted(out, key=lambda x: x["email"])


def run():
    try:
        req = json.load(sys.stdin)
        key = req.get("key") if isinstance(req, dict) else None
        if not isinstance(key, str) or len(key) < 48 or len(key) > 120:
            raise Unsafe("Invalid ephemeral key")
        # Select exactly one OIDC app declared in the live Django runtime
        # config, not any arbitrary SocialAccount or a guessed generic type.
        selector = req.get("provider", "auto")
        selected = selected_oidc_provider(
            getattr(settings, "SOCIALACCOUNT_PROVIDERS", None), selector
        )
        records = read_rows(key, selected)
        print(RESULT_FRAME + json.dumps({"AUDIT": "READ_ONLY", "SYSTEM": "PAPERLESS",
                          "PROVIDER_SELECTION": "CONFIGURED_OIDC_APP",
                          "ACCOUNTS": records, "COUNT": len(records)},
                         sort_keys=True))
    except Unsafe as e:
        code = str(e) if str(e) in PROVIDER_FAILURE_CODES else "OIDC_INSPECTOR_INVALID"
        print(RESULT_FRAME + json.dumps({"AUDIT": "FAILED_CLOSED", "CODE": code}))
        raise SystemExit(2)
    except Exception:
        print(RESULT_FRAME + '{"AUDIT":"FAILED_CLOSED","CODE":"OIDC_INSPECTOR_INTERNAL"}')
        raise SystemExit(2)


run()
