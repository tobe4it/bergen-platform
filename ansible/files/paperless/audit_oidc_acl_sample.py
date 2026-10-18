"""Read-only Paperless Guardian/DRF authorization for OIDC-linked AI identities.

Run through the existing Paperless manage.py shell in its existing container.
Receives a one-use HMAC key and operator-reviewed cases via protected stdin.
Never exports user identifiers, document IDs, content, claims or API responses.
This is NOT a live end-user session or RAG authorization acceptance.
"""
import hashlib
import hmac
import json
import re
import sys

from django.conf import settings
from django.contrib.auth.models import User
from allauth.socialaccount.models import SocialAccount
from documents.models import Document
from documents.permissions import permitted_document_ids
from rest_framework.test import APIClient


FRAME = "BERGEN_PAPERLESS_OIDC_ACL_V1:"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CODES = frozenset({
    "INPUT_INVALID", "ACTORS_INVALID", "DOCS_INVALID", "CASES_INVALID",
    "AUTHORIZATION_MISMATCH", "IDENTITY_AMBIGUOUS", "IDENTITY_UNLINKED",
    "IDENTITY_PRIVILEGED", "OIDC_CONFIG_MISSING", "OIDC_CONFIG_AMBIGUOUS",
    "OIDC_CONFIG_INVALID", "OIDC_PROVIDER_MISSING", "DOC_MISSING",
    "API_CHECK_FAILED",
})


# These statuses refer only to operator-defined A/B aliases. They never
# include usernames, e-mails, provider IDs, subjects or document identifiers.
SAFE_ACTOR_STATES = frozenset({
    "MATCHED", "NO_CONFIGURED_OIDC_LINK", "NOT_LINKED_TO_BERGEN_AI",
    "SUBJECT_MISMATCH", "DUPLICATE_OIDC_LINK",
    "INACTIVE_OR_PRIVILEGED", "SUBJECT_COLLISION",
})


class AuditError(Exception):
    def __init__(self, code, actor_states=None):
        super().__init__(code)
        self.actor_states = actor_states


def demand(cond, code):
    if not cond:
        raise AuditError(code)


def fingerprint(secret, value):
    demand(isinstance(value, str) and bool(value)
           and len(value) <= 1024, "INPUT_INVALID")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def verify_cases(cases, profile="balanced"):
    demand(profile in ("balanced", "no-private-b"), "CASES_INVALID")
    doc_count = 4 if profile == "balanced" else 3
    demand(isinstance(cases, list)
           and len(cases) == doc_count * 2, "CASES_INVALID")
    people, docs, seen = set(), set(), set()
    allow_counts = {}
    deny_counts = {}
    for case in cases:
        demand(isinstance(case, dict)
               and set(case) == {"username", "document_id", "allow"}
               and isinstance(case["username"], str)
               and 1 <= len(case["username"]) <= 100
               and type(case["document_id"]) is int
               and case["document_id"] > 0
               and type(case["allow"]) is bool, "CASES_INVALID")
        name, doc = case["username"], case["document_id"]
        demand((name, doc) not in seen, "CASES_INVALID")
        seen.add((name, doc))
        people.add(name)
        docs.add(doc)
        stat = allow_counts if case["allow"] else deny_counts
        stat[name] = stat.get(name, 0) + 1
    demand(len(people) == 2 and len(docs) == doc_count
           and len(seen) == doc_count * 2, "ACTORS_INVALID")
    for name in people:
        demand(allow_counts.get(name, 0) > 0, "CASES_INVALID")
    # Symmetric baseline requires at least one negative per actor.
    # Without a B-owned private document, one actor remains untested for
    # denial: never silently represent a partial sample as full coverage.
    without_negative = sum(deny_counts.get(name, 0) == 0 for name in people)
    if profile == "balanced":
        demand(without_negative == 0, "CASES_INVALID")
    else:
        demand(without_negative == 1
               and sum(allow_counts.values()) == 5
               and sum(deny_counts.values()) == 1, "CASES_INVALID")
        # Every document must be represented for each user.
    return people, docs, sum(allow_counts.values()), sum(deny_counts.values())


def oidc_provider(config):
    demand(isinstance(config, dict), "OIDC_CONFIG_MISSING")
    data = config.get("openid_connect")
    demand(isinstance(data, dict)
           and isinstance(data.get("APPS"), list)
           and bool(data["APPS"]), "OIDC_CONFIG_MISSING")
    apps = data["APPS"]
    demand(len(apps) == 1, "OIDC_CONFIG_AMBIGUOUS")
    app = apps[0]
    demand(isinstance(app, dict), "OIDC_CONFIG_INVALID")
    provider = app.get("provider_id") or "openid_connect"
    demand(isinstance(provider, str) and
           bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", provider)),
           "OIDC_CONFIG_INVALID")
    return provider


def verify_ai_fingerprints(ai):
    demand(isinstance(ai, dict)
           and ai.get("AUDIT") == "READ_ONLY"
           and ai.get("SYSTEM") == "BERGEN_AI"
           and isinstance(ai.get("ACCOUNTS"), list)
           and ai.get("COUNT") == len(ai["ACCOUNTS"])
           and len(ai["ACCOUNTS"]) <= 1000, "INPUT_INVALID")
    result = {}
    seen_subjects = set()
    for x in ai["ACCOUNTS"]:
        demand(isinstance(x, dict)
               and isinstance(x.get("email"), str)
               and bool(HEX64.fullmatch(x["email"]))
               and isinstance(x.get("subject"), str)
               and bool(HEX64.fullmatch(x["subject"]))
               and x.get("role") in ("USER", "ADMIN", "PENDING"),
               "INPUT_INVALID")
        demand(x["email"] not in result and
               x["subject"] not in seen_subjects, "IDENTITY_AMBIGUOUS")
        result[x["email"]] = x["subject"]
        seen_subjects.add(x["subject"])
    return result


def bind_users(people, ai, key, provider, actor_order=None):
    ai_by_email = verify_ai_fingerprints(ai)
    # Ordered aliases come from the operator-reviewed matrix. Never print
    # the usernames, even when matching fails.
    actor_order = list(actor_order) if actor_order is not None else sorted(people)
    demand(len(actor_order) == 2 and set(actor_order) == people
           and len(set(actor_order)) == 2, "ACTORS_INVALID")
    links = list(
        SocialAccount.objects.filter(provider=provider)
        .select_related("user").order_by("pk")[:1001]
    )
    demand(len(links) <= 1000, "INPUT_INVALID")
    result = {}
    states = {name: "NO_CONFIGURED_OIDC_LINK" for name in people}
    subjects = {}
    for link in links:
        user = link.user
        name = user.username
        if name not in people:
            continue
        # A second link for the same selected user must never overwrite the
        # first binding, even if the earlier link was malformed.
        if states[name] != "NO_CONFIGURED_OIDC_LINK":
            states[name] = "DUPLICATE_OIDC_LINK"
            result.pop(name, None)
            continue
        if not isinstance(user, User) or not user.is_active \
                or user.is_superuser or user.is_staff:
            states[name] = "INACTIVE_OR_PRIVILEGED"
            continue
        email = user.email.strip().casefold() if isinstance(user.email, str) else ""
        email_hash = fingerprint(key, email)
        required_subject = ai_by_email.get(email_hash)
        if required_subject is None:
            states[name] = "NOT_LINKED_TO_BERGEN_AI"
            continue
        extra = link.extra_data or {}
        if not isinstance(extra, dict):
            states[name] = "SUBJECT_MISMATCH"
            continue
        candidates = (link.uid, extra.get("sub"))
        if not any(isinstance(sub, str) and sub and
                   fingerprint(key, sub) == required_subject
                   for sub in candidates):
            states[name] = "SUBJECT_MISMATCH"
            continue
        states[name] = "MATCHED"
        result[name] = user
        subjects[name] = required_subject

    # HMAC subject uniqueness is required independently of per-account
    # matching: one authenticated AI identity must never bind to two users.
    seen = {}
    for name, subject in subjects.items():
        if subject in seen:
            states[name] = "SUBJECT_COLLISION"
            states[seen[subject]] = "SUBJECT_COLLISION"
            result.pop(name, None)
            result.pop(seen[subject], None)
        seen[subject] = name
    if any(state != "MATCHED" for state in states.values()):
        safe = {
            "A": states[actor_order[0]],
            "B": states[actor_order[1]],
        }
        demand(all(s in SAFE_ACTOR_STATES for s in safe.values()),
               "IDENTITY_AMBIGUOUS")
        raise AuditError("IDENTITY_UNLINKED", safe)
    demand(set(result) == people, "IDENTITY_AMBIGUOUS")
    return result

def authorize_examples(cases, users, docs):
    existing = set(Document.objects.filter(pk__in=docs).values_list("pk", flat=True))
    demand(existing == docs, "DOC_MISSING")
    checks = 0
    for case in cases:
        user = users[case["username"]]
        doc_id = case["document_id"]
        expected = case["allow"]
        # This is Paperless's own effective object authorization including
        # owner, guardian user/grp grants and model-level permissions.
        authorized = permitted_document_ids(
            user, perm="view_document"
        ).filter(pk=doc_id).exists()
        checks += 1
        demand(authorized == expected, "AUTHORIZATION_MISMATCH")

        # Independently check the Paperless DRF detail endpoint as this user.
        # No data returned by DRF is saved, logged, sent to an LLM or exported.
        client = APIClient()
        client.force_authenticate(user=user)
        try:
            response = client.get(
                "/api/documents/%d/" % doc_id, HTTP_HOST="127.0.0.1"
            )
            status = response.status_code
            response.close()
        except Exception:
            raise AuditError("API_CHECK_FAILED") from None
        checks += 1
        demand((status == 200) if expected else status in (403, 404),
               "AUTHORIZATION_MISMATCH")
    return checks


def run():
    try:
        request = json.load(sys.stdin)
        demand(isinstance(request, dict), "INPUT_INVALID")
        secret = request.get("key")
        demand(isinstance(secret, str) and 48 <= len(secret) <= 120,
               "INPUT_INVALID")
        cases = request.get("cases")
        profile = request.get("profile", "balanced")
        people, docs, allowed, denied = verify_cases(cases, profile)
        provider = oidc_provider(
            getattr(settings, "SOCIALACCOUNT_PROVIDERS", None)
        )
        # The matrix generator records its account labels in A, B order.
        # Derive aliases from first appearance, never from sorted usernames.
        actor_order = list(dict.fromkeys(case["username"] for case in cases))
        users = bind_users(
            people, request.get("ai"), secret, provider, actor_order
        )
        checks = authorize_examples(cases, users, docs)
        expected_checks = 2 * len(cases)
        demand(checks == expected_checks, "AUTHORIZATION_MISMATCH")
        is_limited = profile == "no-private-b"
        print(FRAME + json.dumps({
            "AUDIT": "READ_ONLY",
            "STATUS": (
                "OIDC_LINKED_PAPERLESS_ACL_SAMPLE_LIMITED"
                if is_limited else "OIDC_LINKED_PAPERLESS_ACL_SAMPLE_PASS"
            ),
            "PROFILE": profile,
            "PER_ACTOR_DENY_COVERAGE": (
                "ONE_ACTOR_UNTESTED" if is_limited
                else "BOTH_ACTORS_TESTED"
            ),
            "ACTORS": 2,
            "DOCUMENTS": len(docs),
            "CASES": len(cases),
            "ALLOWED_CASES": allowed,
            "DENIED_CASES": denied,
            "GUARDIAN_AND_DRF_CHECKS": checks,
            "GUARDIAN_AND_DRF_FAIL": 0,
            "ISSUER_EQUALITY": "NOT_PROVEN",
            "LIVE_USER_DELEGATION": "NOT_PROVEN",
            "AI_RAG_AUTHORIZATION": "NOT_PROVEN",
            "CHILD_ACCESS_SEPARATION": "NOT_PROVEN",
            "GROUP_REVOCATION": "NOT_PROVEN",
            "CHANGED": False
        }, sort_keys=True))
    except AuditError as e:
        code = str(e) if str(e) in CODES else "AUDIT_INTERNAL_ERROR"
        message = {"AUDIT": "FAILED_CLOSED", "CODE": code}
        if (code == "IDENTITY_UNLINKED"
            and isinstance(e.actor_states, dict)
            and set(e.actor_states) == {"A", "B"}
            and all(s in SAFE_ACTOR_STATES for s in e.actor_states.values())):
            message["ACCOUNT_A_LINK"] = e.actor_states["A"]
            message["ACCOUNT_B_LINK"] = e.actor_states["B"]
        print(FRAME + json.dumps(message, sort_keys=True))
        raise SystemExit(2)
    except Exception:
        print(FRAME + '{"AUDIT":"FAILED_CLOSED","CODE":"AUDIT_INTERNAL_ERROR"}')
        raise SystemExit(2)


run()
