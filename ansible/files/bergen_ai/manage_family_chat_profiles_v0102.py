"""Open WebUI v0.10.2: OIDC-active private-only four-profile staging.

API only (never SQL writes). Secrets, model prompts and raw API errors are
never printed. Existing user/group membership and OIDC config are untouched.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)

APP = "http://127.0.0.1:3000"
OLLAMA = "http://127.0.0.1:11434"
PREFIX = "BERGEN_FAMILY_MODEL_STAGE_V1:"
ALLOWED_MODES = {"audit", "apply", "rollback"}
MODEL_A = "qwen2.5:14b-instruct-q4_K_M"
MODEL_B = "mistral-nemo:12b"
PARENT_PROMPT = (
    "Du bist Bergen-AI, ein präziser und zuverlässiger Familienassistent "
    "für Erwachsene. Erkläre nachvollziehbar und unterscheide Fakten "
    "von Vermutungen. Du hast keinen automatischen Zugriff auf Paperless, "
    "private Daten anderer Nutzer, Werkzeuge oder externe Websuche."
)


class Refuse(Exception):
    def __init__(self, code):
        self.code = code


def demand(check, code):
    if not check:
        raise Refuse(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def get_json(path, token=None, base=APP):
    return call_json("GET", path, None, token, base)


def call_json(method, path, payload, token=None, base=APP):
    demand(path.startswith("/") and "://" not in path and "?" not in path,
           "BAD_REQUEST_PATH")
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
    body = None if payload is None else json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = Request(base + path, data=body, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=12) as response:
            demand(response.status in (200, 201), "API_UNREVIEWED_RESPONSE")
            data = response.read(400001)
        demand(len(data) <= 400000, "API_RESPONSE_TOO_LARGE")
        return json.loads(data)
    except (HTTPError, URLError, OSError, ValueError, TypeError):
        raise Refuse("API_UNAVAILABLE_OR_DENIED") from None


def checked_version():
    data = get_json("/api/version")
    demand(isinstance(data, dict) and
           data.get("version") in ("0.10.2", "v0.10.2"),
           "UNREVIEWED_OPEN_WEBUI_VERSION")


def check_guest(names):
    inspect = json.loads(subprocess.check_output(
        ["podman", "inspect", "open-webui"],
        stderr=subprocess.DEVNULL, timeout=12, text=True))
    demand(isinstance(inspect, list) and len(inspect) == 1,
           "UNREVIEWED_GUEST")
    sources = [m.get("Source") for m in inspect[0].get("Mounts", [])
               if m.get("Destination") == "/app/backend/data"]
    demand(sources == ["/srv/ai/open-webui"], "DATA_MOUNT_DRIFT")
    env = inspect[0].get("Config", {}).get("Env")
    demand(isinstance(env, list), "ENV_DRIFT")
    values = dict(x.split("=", 1) for x in env
                  if isinstance(x, str) and "=" in x)
    demand(values.get("BYPASS_MODEL_ACCESS_CONTROL", "false").lower() != "true",
           "MODEL_ACL_BYPASSED")
    demand(values.get("ENABLE_OAUTH_GROUP_MANAGEMENT", "false").lower() == "true",
           "OIDC_GROUP_MANAGEMENT_NOT_ACTIVE")
    demand(values.get("ENABLE_OAUTH_GROUP_CREATION", "false").lower() != "true"
           and values.get("ENABLE_OAUTH_ROLE_MANAGEMENT", "false").lower() != "true"
           and values.get("ENABLE_OAUTH_PERSISTENT_CONFIG", "false").lower() == "false",
           "OIDC_PRIVILEGE_BASELINE_DRIFT")
    demand(not any(x in values for x in
                   ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")),
           "DATABASE_BACKEND_UNREVIEWED")
    db_file = Path(sources[0]) / "webui.db"
    demand(db_file.is_file() and not db_file.is_symlink(),
           "DATABASE_NOT_FOUND")
    # First-stage release now targets the VERIFIED OIDC-synchronized
    # adult+family baseline. Members can see newly granted aliases immediately;
    # fingerprint roster and fail if accounts/groups move between audit/apply.
    uri = db_file.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=4) as db:
        db.execute("PRAGMA query_only=ON")
        member_count = db.execute(
            'SELECT COUNT(*) FROM "group_member"').fetchone()[0]
        existing_grants = db.execute(
            "SELECT COUNT(*) FROM access_grant WHERE resource_type='model'"
        ).fetchone()[0]
        all_model_ids = {r[0] for r in db.execute('SELECT id FROM "model"')}
        members = db.execute(
            'SELECT gm.user_id, g.name FROM group_member gm '
            'JOIN "group" g ON g.id=gm.group_id'
        ).fetchall()
        # Members are already present because OIDC sync is active. Only
        # same-family user/group assignments are permitted. No account IDs or
        # group names are ever printed; the roster is merely fingerprinted.
        existing_names = {r[0] for r in db.execute('SELECT name FROM "group"')}
        demand(existing_names == set(names.values()), "GROUP_SET_DRIFT")
        demand(len(members) == member_count
               and 0 < len(members) <= 12
               and all(isinstance(uid, str) and uid and group in existing_names
                       for uid, group in members),
               "GROUP_MEMBERSHIP_REVIEW_REQUIRED")
        adult = {uid for uid, group in members if group == names["adults"]}
        child = {uid for uid, group in members if group == names["children"]}
        family = {uid for uid, group in members if group == names["family"]}
        demand(bool(adult) and not (adult & child)
               and (adult | child).issubset(family),
               "GROUP_MEMBERSHIP_REVIEW_REQUIRED")
        roles = dict(db.execute('SELECT id, role FROM "user"').fetchall())
        demand(all(roles.get(uid) in ("user", "pending", "admin")
                   for uid, _ in members),
               "GROUP_MEMBERSHIP_REVIEW_REQUIRED")
        demand(all(roles.get(uid) == "user" for uid in adult),
               "GROUP_MEMBERSHIP_REVIEW_REQUIRED")
    demand(existing_grants == 0 or existing_grants == 4,
           "MODEL_GRANT_BASELINE_DRIFT")
    roster_hash = hashlib.sha256(json.dumps(
        sorted(members), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return all_model_ids, roster_hash


def validate_names(names):
    demand(isinstance(names, dict) and
           set(names) == {"adults", "children", "family"},
           "GROUP_NAMES_UNREVIEWED")
    values = list(names.values())
    demand(all(isinstance(name, str) and name == name.strip()
               and 1 <= len(name) <= 120 for name in values)
           and len(set(values)) == 3, "GROUP_NAMES_UNREVIEWED")


def profile_plan(ids, prompt):
    return [
        {"id": "bergen-eltern-qwen25", "base_model_id": MODEL_A,
         "name": "Bergen AI – Eltern", "role": "adults", "prompt": PARENT_PROMPT},
        {"id": "bergen-kinder-lernen", "base_model_id": MODEL_A,
         "name": "Bergen AI – Lernbegleiter", "role": "children",
         "prompt": prompt},
        {"id": "bergen-eltern-sprachen", "base_model_id": MODEL_B,
         "name": "Bergen AI – Sprachen", "role": "adults", "prompt": PARENT_PROMPT},
        {"id": "bergen-kinder-sprachen", "base_model_id": MODEL_B,
         "name": "Bergen AI – Sprachtrainer", "role": "children",
         "prompt": prompt},
    ]


def as_payload(plan, ids):
    return {
        "id": plan["id"],
        "base_model_id": plan["base_model_id"],
        "name": plan["name"],
        "meta": {"description": "Privates Bergen-AI Gruppenmodell"},
        "params": {"system": plan["prompt"]},
        "access_grants": [{
            "principal_type": "group",
            "principal_id": ids[plan["role"]],
            "permission": "read"
        }],
        "is_active": True,
    }


def grant_ok(record, group_id):
    grants = record.get("access_grants")
    return isinstance(grants, list) and len(grants) == 1 and all(
        g.get("principal_type") == "group"
        and g.get("principal_id") == group_id
        and g.get("permission") == "read"
        for g in grants if isinstance(g, dict)
    ) and all(isinstance(g, dict) for g in grants)


def matches_existing(record, plan, ids):
    param = record.get("params")
    return (
        record.get("id") == plan["id"]
        and record.get("base_model_id") == plan["base_model_id"]
        and record.get("name") == plan["name"]
        and record.get("is_active") is True
        and isinstance(param, dict)
        and param.get("system") == plan["prompt"]
        and grant_ok(record, ids[plan["role"]])
    )


def fetch_state(token, names, prompt):
    checked_version()
    db_model_ids, membership_hash = check_guest(names)
    oauth = get_json("/api/v1/auths/admin/config/oauth", token)
    demand(isinstance(oauth, dict)
           and oauth.get("ENABLE_OAUTH_GROUP_MANAGEMENT") is True
           and oauth.get("ENABLE_OAUTH_GROUP_CREATION") is False
           and oauth.get("ENABLE_OAUTH_ROLE_MANAGEMENT") is False,
           "EFFECTIVE_OIDC_CONFIG_DRIFT")
    groups = get_json("/api/v1/groups/", token)
    demand(isinstance(groups, list) and len(groups) == 3,
           "GROUP_SET_DRIFT")
    demand({g.get("name") for g in groups if isinstance(g, dict)}
           == set(names.values()), "GROUP_SET_DRIFT")
    ids = {}
    for key, name in names.items():
        candidates = [g.get("id") for g in groups
                      if isinstance(g, dict) and g.get("name") == name]
        demand(len(candidates) == 1 and
               isinstance(candidates[0], str) and candidates[0],
               "GROUP_ID_UNREVIEWED")
        ids[key] = candidates[0]
    ollama = get_json("/api/tags", base=OLLAMA)
    model_list = ollama.get("models") if isinstance(ollama, dict) else None
    demand(isinstance(model_list, list) and len(model_list) <= 300,
           "OLLAMA_MODEL_LIST_INVALID")
    names_available = {
        item.get("name") for item in model_list
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    demand({MODEL_A, MODEL_B}.issubset(names_available),
           "REQUIRED_OLLAMA_MODELS_MISSING")
    models = get_json("/api/v1/models/list", token)
    demand(isinstance(models, dict) and
           isinstance(models.get("items"), list) and
           isinstance(models.get("total"), int) and
           len(models["items"]) == models["total"] and
           len(models["items"]) <= 20,
           "MODEL_LIST_UNREVIEWED")
    entries = models["items"]
    demand(all(isinstance(x, dict) and isinstance(x.get("id"), str)
               for x in entries), "MODEL_LIST_UNREVIEWED")
    plan = profile_plan(ids, prompt)
    expected_ids = {p["id"] for p in plan}
    current_ids = {m["id"] for m in entries}
    demand(current_ids == db_model_ids, "MODEL_DB_API_MISMATCH")
    if not entries:
        stage = "EMPTY_READY"
    elif current_ids == expected_ids and len(entries) == len(expected_ids):
        stage = "ALREADY_STAGED" if all(
            matches_existing(next(m for m in entries if m["id"] == p["id"]),
                             p, ids) for p in plan
        ) else "PROFILE_DRIFT"
    else:
        stage = "PROFILE_DRIFT"
    # Opaque snapshot, no user data or secret/identity fields in output.
    snap = {
        "group_id_map": ids,
        "membership_fingerprint": membership_hash,
        "oidc_group_management": "ACTIVE",
        "model_ids": sorted(current_ids),
        "profile_state": stage,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "installed_models": sorted([MODEL_A, MODEL_B]),
        "version": "0.10.2",
    }
    fingerprint = hashlib.sha256(json.dumps(
        snap, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return stage, fingerprint, plan, ids


def response(**kwargs):
    print(PREFIX + json.dumps(kwargs, sort_keys=True), flush=True)


def run():
    try:
        inp = json.load(sys.stdin)
        demand(isinstance(inp, dict), "INPUT_UNREVIEWED")
        mode = inp.get("mode")
        demand(mode in ALLOWED_MODES, "MODE_INVALID")
        token = inp.get("token")
        demand(isinstance(token, str) and len(token) >= 20, "TOKEN_UNAVAILABLE")
        names = inp.get("expected_groups")
        validate_names(names)
        prompt = inp.get("child_prompt")
        demand(isinstance(prompt, str)
               and 1000 <= len(prompt) <= 15000
               and "Vorsagen untersagt" in prompt
               and "Gilt für beide Kinder-Chatprofile" in prompt,
               "CHILD_POLICY_MISSING")
        stage, sha, plan, ids = fetch_state(token, names, prompt)
        if mode == "audit":
            response(AUDIT="READ_ONLY", STATUS=stage,
                     CONFIG_SHA256=sha, MODEL_COUNT=(0 if stage == "EMPTY_READY" else 4)
                     if stage != "PROFILE_DRIFT" else -1,
                     REQUIRED_MODELS_PRESENT="YES", CHANGED=False,
                     GROUP_MEMBERSHIP_CHANGES="NONE",
                     OIDC_CHANGES="NONE")
            return
        demand(inp.get("approved") is True
               and inp.get("backup_verified") is True,
               "APPROVAL_OR_BACKUP_MISSING")
        demand(inp.get("expected_sha256") == sha, "SNAPSHOT_CHANGED")
        demand(stage != "PROFILE_DRIFT", "PROFILE_DRIFT")
        if mode == "apply":
            if stage == "ALREADY_STAGED":
                response(AUDIT="CONTROLLED", STATUS="ALREADY_STAGED",
                         CREATED=0, CHANGED=False)
                return
            demand(stage == "EMPTY_READY", "UNEXPECTED_STATE")
            done = 0
            for plan_item in plan:
                result = call_json("POST", "/api/v1/models/create",
                                   as_payload(plan_item, ids), token)
                demand(isinstance(result, dict)
                       and result.get("id") == plan_item["id"],
                       "MODEL_CREATE_REQUIRES_REVIEW")
                done += 1
            final_stage, _, _, _ = fetch_state(token, names, prompt)
            demand(final_stage == "ALREADY_STAGED",
                   "MODEL_POSTCHECK_REQUIRES_REVIEW")
            response(AUDIT="CONTROLLED", STATUS="PRIVATE_PROFILES_STAGED",
                     CREATED=done, CHANGED=True,
                     USER_MEMBERSHIPS_CHANGED=False,
                     MODEL_ACL_PUBLIC="NO")
        elif mode == "rollback":
            demand(inp.get("rollback_approved") is True,
                   "ROLLBACK_NOT_APPROVED")
            demand(stage == "ALREADY_STAGED", "ROLLBACK_STATE_UNREVIEWED")
            removed = 0
            for plan_item in reversed(plan):
                result = call_json("POST", "/api/v1/models/model/delete",
                                   {"id": plan_item["id"]}, token)
                demand(result is True, "ROLLBACK_REQUIRES_REVIEW")
                removed += 1
            stage2, _, _, _ = fetch_state(token, names, prompt)
            demand(stage2 == "EMPTY_READY", "ROLLBACK_REQUIRES_REVIEW")
            response(AUDIT="CONTROLLED", STATUS="PROFILES_ROLLED_BACK",
                     REMOVED=removed, CHANGED=True)
    except Refuse as exc:
        codes = {
            "BAD_REQUEST_PATH", "API_UNREVIEWED_RESPONSE",
            "API_RESPONSE_TOO_LARGE", "API_UNAVAILABLE_OR_DENIED",
            "UNREVIEWED_OPEN_WEBUI_VERSION", "UNREVIEWED_GUEST",
            "DATA_MOUNT_DRIFT", "ENV_DRIFT", "MODEL_ACL_BYPASSED",
            "OIDC_GROUP_MANAGEMENT_UNREVIEWED",
            "EFFECTIVE_OIDC_CONFIG_DRIFT", "MODEL_DB_API_MISMATCH",
            "DATABASE_BACKEND_UNREVIEWED", "DATABASE_NOT_FOUND",
            "GROUP_MEMBERSHIP_REVIEW_REQUIRED", "MODEL_GRANT_BASELINE_DRIFT",
            "GROUP_NAMES_UNREVIEWED", "GROUP_SET_DRIFT",
            "GROUP_ID_UNREVIEWED", "OLLAMA_MODEL_LIST_INVALID",
            "REQUIRED_OLLAMA_MODELS_MISSING", "MODEL_LIST_UNREVIEWED",
            "INPUT_UNREVIEWED", "MODE_INVALID", "TOKEN_UNAVAILABLE",
            "CHILD_POLICY_MISSING", "APPROVAL_OR_BACKUP_MISSING",
            "SNAPSHOT_CHANGED", "PROFILE_DRIFT", "UNEXPECTED_STATE",
            "MODEL_CREATE_REQUIRES_REVIEW", "MODEL_POSTCHECK_REQUIRES_REVIEW",
            "ROLLBACK_NOT_APPROVED", "ROLLBACK_STATE_UNREVIEWED",
            "ROLLBACK_REQUIRES_REVIEW",
        }
        response(AUDIT="FAILED_CLOSED", STATUS=exc.code if exc.code in codes
                 else "UNREVIEWED_ERROR", CHANGED="UNKNOWN")
        raise SystemExit(2)
    except Exception:
        response(AUDIT="FAILED_CLOSED", STATUS="UNCLASSIFIED_RUNTIME_ERROR",
                 CHANGED="UNKNOWN")
        raise SystemExit(2)


if __name__ == "__main__":
    run()
