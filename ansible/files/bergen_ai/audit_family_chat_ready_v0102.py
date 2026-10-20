"""Tokenless, immutable Bergen-AI model-profile readiness audit for WebUI 0.10.2.

Only inventories local Ollama, existing OIDC-mapped group roster and WebUI
model/grant tables. No direct database writes and no user/group/secret output.
The browser administrator or authenticated supported model API will create
profiles in a separate approved operation.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

PREFIX = "BERGEN_AI_FAMILY_MODELS_READINESS_V1:"
APP = "http://127.0.0.1:3000"
OLLAMA = "http://127.0.0.1:11434"
REQUIRED = {"qwen2.5:14b-instruct-q4_K_M", "mistral-nemo:12b"}
ALIASES = {
    "bergen-eltern-qwen25", "bergen-eltern-sprachen",
    "bergen-kinder-lernen", "bergen-kinder-sprachen"
}


class Refuse(Exception):
    pass


def need(condition, code):
    if not condition:
        raise Refuse(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = build_opener(ProxyHandler({}), NoRedirect())


def fetch(url):
    need(url in (APP + "/api/version", OLLAMA + "/api/tags"),
         "URL_UNREVIEWED")
    with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
        need(response.status == 200, "API_NOT_READY")
        body = response.read(200001)
    need(len(body) < 200001, "API_RESPONSE_TOO_LARGE")
    return json.loads(body)


def check_env():
    inspect = json.loads(subprocess.check_output(
        ["podman", "inspect", "open-webui"],
        stderr=subprocess.DEVNULL, timeout=12, text=True))
    need(isinstance(inspect, list) and len(inspect) == 1, "CONTAINER_UNREVIEWED")
    obj = inspect[0]
    mounts = [m.get("Source") for m in obj.get("Mounts", [])
              if m.get("Destination") == "/app/backend/data"]
    need(mounts == ["/srv/ai/open-webui"], "DATA_MOUNT_DRIFT")
    items = obj.get("Config", {}).get("Env", [])
    need(isinstance(items, list), "ENV_UNREVIEWED")
    config = dict(v.split("=", 1) for v in items
                  if isinstance(v, str) and "=" in v)
    need(config.get("ENABLE_OAUTH_GROUP_MANAGEMENT") == "true"
         and config.get("ENABLE_OAUTH_PERSISTENT_CONFIG", "false") == "false"
         and config.get("ENABLE_OAUTH_ROLE_MANAGEMENT", "false") == "false"
         and config.get("ENABLE_OAUTH_GROUP_CREATION", "false") == "false"
         and config.get("BYPASS_MODEL_ACCESS_CONTROL", "false") == "false",
         "OIDC_OR_ACL_BASELINE_DRIFT")
    return Path("/srv/ai/open-webui/webui.db")


def audit(names, child_prompt):
    need(isinstance(names, dict) and set(names) == {"family", "adults", "children"}
         and len(set(names.values())) == 3
         and all(isinstance(v, str) and v.strip() == v
                 and 1 <= len(v) <= 120 for v in names.values()),
         "THREE_PRIVATE_GROUPS_REQUIRED")
    need(isinstance(child_prompt, str) and
         1000 <= len(child_prompt) <= 15000 and
         "Vorsagen untersagt" in child_prompt and
         "Gilt für beide Kinder-Chatprofile" in child_prompt,
         "LEARNING_PROMPT_UNREVIEWED")

    version = fetch(APP + "/api/version")
    need(isinstance(version, dict) and version.get("version") in ("0.10.2", "v0.10.2"),
         "WEBUI_VERSION_UNREVIEWED")
    db_path = check_env()
    need(db_path.is_file() and not db_path.is_symlink(), "DATABASE_UNREVIEWED")

    tags = fetch(OLLAMA + "/api/tags")
    need(isinstance(tags, dict) and isinstance(tags.get("models"), list)
         and len(tags["models"]) <= 300, "OLLAMA_MODEL_LIST_UNREVIEWED")
    installed = {row.get("name") for row in tags["models"]
                 if isinstance(row, dict) and isinstance(row.get("name"), str)}
    missing = len(REQUIRED - installed)

    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro",
                         uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        need({"group", "group_member", "model", "access_grant", "user"}.issubset(tables),
             "DB_SCHEMA_UNREVIEWED")
        groups = db.execute('SELECT id,name FROM "group"').fetchall()
        need(len(groups) == 3 and
             {g[1] for g in groups} == set(names.values()),
             "GROUPS_UNREVIEWED")
        members = db.execute(
            'SELECT m.user_id, g.name FROM "group_member" m '
            'JOIN "group" g ON g.id=m.group_id'
        ).fetchall()
        need(len(members) > 0 and len(members) <= 12,
             "MEMBERSHIP_UNREVIEWED")
        adult = {uid for uid, name in members if name == names["adults"]}
        child = {uid for uid, name in members if name == names["children"]}
        family = {uid for uid, name in members if name == names["family"]}
        roles = dict(db.execute('SELECT id,role FROM "user"').fetchall())
        need(bool(adult) and not (adult & child)
             and (adult | child).issubset(family)
             and all(roles.get(uid) in ("user", "pending", "admin")
                     for uid, _ in members)
             and all(roles.get(uid) == "user" for uid in adult),
             "MEMBERSHIP_BASELINE_DRIFT")
        models = {r[0] for r in db.execute('SELECT id FROM "model"').fetchall()}
        grants = db.execute(
            "SELECT resource_id,principal_type,principal_id,permission "
            "FROM access_grant WHERE resource_type='model'"
        ).fetchall()
        active_models = len(models)
        need(active_models <= 30 and len(grants) <= 100,
             "MODEL_INVENTORY_TOO_LARGE")
        public_grants = sum(1 for row in grants
                            if row[1] == "user" and row[2] == "*")
        ready = len(models) == 0 and len(grants) == 0
        known_aliases = models == ALIASES
        fingerprint = hashlib.sha256(json.dumps({
            "version": version["version"],
            "groups": sorted(groups),
            "membership": sorted(members),
            "registered_ids": sorted(models),
            "access_grants": sorted(grants),
            "installed_bases": sorted(REQUIRED & installed),
            "prompt_sha256": hashlib.sha256(child_prompt.encode()).hexdigest(),
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    return {
        "AUDIT": "READ_ONLY",
        "CHANGED": False,
        "STATUS": ("READY_FOR_PRIVATE_PROFILES" if ready and not missing
                   else "BASE_MODELS_MISSING" if missing
                   else "PROFILE_INVENTORY_PRESENT" if known_aliases
                   else "MODEL_OR_ACL_BASELINE_DRIFT"),
        "GROUP_SYNC_CONFIGURED": "ON",
        "ADULT_MEMBERS": len(adult),
        "FAMILY_MEMBERS": len(family),
        "CHILD_MEMBERS": len(child),
        "ADULT_CHILD_OVERLAP": "NONE",
        "REGISTERED_MODELS": active_models,
        "MODEL_GRANTS": len(grants),
        "PUBLIC_MODEL_GRANTS": public_grants,
        "REQUIRED_BASE_MODELS_MISSING": missing,
        "CHILD_PROMPT_POLICY": "VALIDATED_SOURCE",
        "CONFIG_SHA256": fingerprint,
        "MODEL_CREATION_PERFORMED": "NO",
        "OIDC_OR_USER_CHANGES": "NONE",
        "MODEL_API_AUTHENTICATION_REQUIRED_FOR_WRITES": "YES"
    }


def main():
    try:
        data = json.load(sys.stdin)
        need(isinstance(data, dict), "INPUT_UNREVIEWED")
        result = audit(data.get("names"), data.get("child_prompt"))
        print(PREFIX + json.dumps(result, sort_keys=True), flush=True)
    except Refuse as err:
        print(PREFIX + json.dumps({
            "AUDIT": "FAILED_CLOSED",
            "STATUS": str(err),
            "CHANGED": False,
        }, sort_keys=True), flush=True)
        sys.exit(2)
    except Exception:
        print(PREFIX + json.dumps({
            "AUDIT": "FAILED_CLOSED",
            "STATUS": "UNCLASSIFIED_READONLY_ERROR",
            "CHANGED": False,
        }, sort_keys=True), flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
