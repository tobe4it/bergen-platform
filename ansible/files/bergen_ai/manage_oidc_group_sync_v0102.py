"""Open WebUI 0.10.2: guarded activation of existing OIDC GROUP sync.

No user/group/model/direct-SQL writes, no OAuth client changes, no restarts.
Uses the running administrator API only. Never prints API tokens, identities,
raw claim values, full OAuth config or provider secrets.

Safety limitation: Open WebUI 0.10.2 does not revoke retained memberships
when the received OAuth groups claim is empty/missing. Audit reports this
limit explicitly; independent membership/session revocation remains required.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

FRAME = "BERGEN_OIDC_GROUP_SYNC_V1:"
BASE = "http://127.0.0.1:3000"
MODEL_IDS = {
    "bergen-eltern-qwen25": "adults",
    "bergen-kinder-lernen": "children",
    "bergen-eltern-sprachen": "adults",
    "bergen-kinder-sprachen": "children",
}
DATA = Path("/srv/ai/open-webui/webui.db")


class Reject(Exception):
    pass


def require(yes, reason):
    if not yes:
        raise Reject(reason)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def api(method, endpoint, token, data=None):
    require(endpoint.startswith("/api/") and "?" not in endpoint and
            "://" not in endpoint, "API_PATH_INVALID")
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data, separators=(",", ":")).encode()
    try:
        request = Request(BASE + endpoint, data=body, method=method,
                          headers=headers)
        with OPENER.open(request, timeout=15) as response:
            require(response.status in (200, 201), "API_RESPONSE_UNREVIEWED")
            raw = response.read(256001)
        require(len(raw) <= 256000, "API_RESPONSE_TOO_LARGE")
        return json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        raise Reject("ADMIN_API_UNAVAILABLE_OR_DENIED") from None


def group_names(request):
    names = request.get("groups")
    require(isinstance(names, dict) and
            set(names) == {"family", "adults", "children"},
            "GROUP_MAPPING_UNREVIEWED")
    values = list(names.values())
    require(len(set(values)) == 3 and all(
        isinstance(value, str) and value == value.strip()
        and 1 <= len(value) <= 120 for value in values
    ), "GROUP_MAPPING_UNREVIEWED")
    return names


def current(token, names):
    v = api("GET", "/api/version", token)
    require(isinstance(v, dict) and
            v.get("version") in ("0.10.2", "v0.10.2"),
            "VERSION_UNREVIEWED")
    oauth = api("GET", "/api/v1/auths/admin/config/oauth", token)
    admin = api("GET", "/api/v1/auths/admin/config", token)
    groups = api("GET", "/api/v1/groups/", token)
    require(isinstance(oauth, dict) and isinstance(admin, dict)
            and isinstance(groups, list), "API_SCHEMA_UNREVIEWED")
    for k in ("ENABLE_OAUTH_GROUP_MANAGEMENT",
              "ENABLE_OAUTH_GROUP_CREATION",
              "ENABLE_OAUTH_ROLE_MANAGEMENT"):
        require(type(oauth.get(k)) is bool, "OAUTH_FLAGS_UNREVIEWED")
    require(oauth["ENABLE_OAUTH_GROUP_CREATION"] is False
            and oauth["ENABLE_OAUTH_ROLE_MANAGEMENT"] is False,
            "ROLE_OR_GROUP_CREATION_UNREVIEWED")
    require(admin.get("DEFAULT_USER_ROLE") == "pending",
            "DEFAULT_ROLE_MUST_REMAIN_PENDING")
    require(admin.get("ENABLE_API_KEYS") is True,
            "ADMIN_API_KEYS_NOT_ENABLED")
    scopes = oauth.get("OAUTH_SCOPES")
    require(isinstance(scopes, str) and
            "groups" in scopes.split(), "OIDC_GROUP_SCOPE_MISSING")
    require(oauth.get("OAUTH_GROUP_CLAIM") in ("", None, "groups"),
            "OIDC_CLAIM_UNREVIEWED")
    actual = {g.get("name"): g.get("id") for g in groups
              if isinstance(g, dict) and isinstance(g.get("name"), str)}
    require(len(groups) == len(actual) == 3 and
            set(actual) == set(names.values()) and
            all(isinstance(v, str) and v for v in actual.values()),
            "EXACT_THREE_GROUPS_REQUIRED")
    gid = {role: actual[name] for role, name in names.items()}

    require(DATA.is_file() and not DATA.is_symlink(), "WEBUI_DATABASE_UNREVIEWED")
    with sqlite3.connect(DATA.resolve().as_uri() + "?mode=ro",
                         uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute('SELECT id FROM "model"').fetchall()
        model_ids = {row[0] for row in rows}
        grants = db.execute(
            "SELECT resource_id,principal_type,principal_id,permission "
            "FROM access_grant WHERE resource_type='model'").fetchall()
        members = db.execute(
            'SELECT COUNT(*) FROM "group_member"').fetchone()[0]

    expected_grants = {
        (model_id, "group", gid[role], "read")
        for model_id, role in MODEL_IDS.items()
    }
    model_ready = (
        model_ids == set(MODEL_IDS)
        and len(rows) == len(MODEL_IDS)
        and set(grants) == expected_grants
        and len(grants) == len(expected_grants)
    )

    # Full OAuth configuration hashed, never printed (includes sensitive keys).
    stamp = {
        "oauth_config": oauth,
        "admin_key_allowed": admin["ENABLE_API_KEYS"],
        "default_role": admin["DEFAULT_USER_ROLE"],
        "group_ids": gid,
        "model_private": model_ready,
        "members": members,
    }
    digest = hashlib.sha256(json.dumps(
        stamp, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return oauth, digest, model_ready, members


def status(**fields):
    print(FRAME + json.dumps(fields, sort_keys=True), flush=True)


def run():
    try:
        request = json.load(sys.stdin)
        require(isinstance(request, dict)
                and request.get("protocol") == "group-sync-v1",
                "INPUT_UNREVIEWED")
        mode = request.get("mode")
        require(mode in ("audit", "apply", "rollback"), "MODE_UNREVIEWED")
        token = request.get("token")
        require(isinstance(token, str) and len(token) >= 20,
                "ADMIN_TOKEN_MISSING")
        names = group_names(request)
        oauth, fingerprint, profiles_ready, members = current(token, names)
        enabled = oauth["ENABLE_OAUTH_GROUP_MANAGEMENT"]
        if mode == "audit":
            status(AUDIT="READ_ONLY",
                   STATUS="ENABLED" if enabled else (
                       "READY" if profiles_ready else "PRIVATE_PROFILES_MISSING"),
                   PROFILES_PRIVATE_READY=profiles_ready,
                   MEMBER_COUNT=members,
                   GROUP_CLAIM="GROUPS" if oauth.get("OAUTH_GROUP_CLAIM") == "groups"
                   else "NOT_EXPLICIT",
                   CONFIG_SHA256=fingerprint,
                   EMPTY_OR_MISSING_CLAIM_REVOCATION="NOT_SUPPORTED_BY_V0_10_2",
                   SESSION_REVOCATION="NOT_PROVEN",
                   CHANGED=False)
            return
        require(request.get("approved") is True
                and request.get("backup_verified") is True,
                "BACKUP_OR_APPROVAL_MISSING")
        require(request.get("expected_sha256") == fingerprint,
                "CONFIG_FINGERPRINT_CHANGED")
        if mode == "apply":
            require(not enabled, "ALREADY_ENABLED")
            require(profiles_ready, "PRIVATE_PROFILES_MISSING")
            require(members == 0, "INITIAL_MEMBERSHIP_NOT_EMPTY")
            payload = {"ENABLE_OAUTH_GROUP_MANAGEMENT": True,
                       "ENABLE_OAUTH_GROUP_CREATION": False,
                       "ENABLE_OAUTH_ROLE_MANAGEMENT": False,
                       "OAUTH_GROUP_CLAIM": "groups"}
        else:
            require(enabled, "ALREADY_DISABLED")
            require(request.get("rollback_approved") is True,
                    "ROLLBACK_APPROVAL_MISSING")
            payload = {"ENABLE_OAUTH_GROUP_MANAGEMENT": False}
        result = api("POST", "/api/v1/auths/admin/config/oauth", token, payload)
        require(isinstance(result, dict), "OAUTH_RESPONSE_UNREVIEWED")
        updated, _new_fp, ready_after, after_members = current(token, names)
        require(updated["ENABLE_OAUTH_GROUP_MANAGEMENT"] is
                (mode == "apply"), "POSTCHECK_FAILED")
        require(updated["ENABLE_OAUTH_GROUP_CREATION"] is False
                and updated["ENABLE_OAUTH_ROLE_MANAGEMENT"] is False,
                "POSTCHECK_FAILED")
        require(updated.get("OAUTH_GROUP_CLAIM") == "groups"
                if mode == "apply" else True, "POSTCHECK_FAILED")
        allowed_changed = set(payload)
        require(all(updated.get(k) == v for k, v in oauth.items()
                    if k not in allowed_changed),
                "UNEXPECTED_OAUTH_CHANGE")
        if mode == "apply":
            require(ready_after and after_members == 0,
                    "POSTCHECK_FAILED")
        status(AUDIT="CONTROLLED",
               STATUS="GROUP_SYNC_ENABLED" if mode == "apply"
               else "GROUP_SYNC_DISABLED_MEMBERSHIP_REVIEW_REQUIRED",
               CHANGED=True,
               ROLE_MANAGEMENT="OFF",
               GROUP_CREATION="OFF",
               DEFAULT_USER_ROLE="PENDING",
               SESSION_REVOCATION="NOT_PROVEN",
               EMPTY_OR_MISSING_CLAIM_REVOCATION="NOT_SUPPORTED_BY_V0_10_2",
               REMAINING_GROUP_MEMBERS=after_members)
    except Reject as exc:
        status(AUDIT="FAILED_CLOSED", STATUS=str(exc),
               CHANGED="UNKNOWN")
        raise SystemExit(2)
    except Exception:
        status(AUDIT="FAILED_CLOSED", STATUS="UNCLASSIFIED_FAILURE",
               CHANGED="UNKNOWN")
        raise SystemExit(2)


if __name__ == "__main__":
    run()
