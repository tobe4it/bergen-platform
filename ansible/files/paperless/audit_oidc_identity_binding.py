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
from allauth.socialaccount.models import SocialAccount


class Unsafe(Exception):
    pass


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
        records = read_rows(key, req.get("provider"))
        print(json.dumps({"AUDIT": "READ_ONLY", "SYSTEM": "PAPERLESS",
                          "ACCOUNTS": records, "COUNT": len(records)},
                         sort_keys=True))
    except Exception:
        print('{"AUDIT":"FAILED_CLOSED"}')
        raise SystemExit(2)


run()
