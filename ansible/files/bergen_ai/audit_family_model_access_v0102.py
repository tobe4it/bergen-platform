"""Bergen-AI v0.10.2: non-mutating family model access preflight.

Read-only SQLite + Podman mount identity. No token, user IDs, group names,
model text, or private paths printed. Does NOT authorize activating groups.
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROLES = ("family", "adults", "children")
MODEL_TAGS = (
    "qwen2.5:14b-instruct-q4_K_M",
    "mistral-nemo:12b",
    "bge-m3:latest",
)
FRAME = "BERGEN_FAMILY_MODEL_ACCESS_V1:"


class Refuse(Exception):
    pass


def demand(ok):
    if not ok:
        raise Refuse


def names_ok(data):
    demand(isinstance(data, dict) and set(data) == set(ROLES))
    values = [data[k] for k in ROLES]
    demand(all(isinstance(v, str) and v and v == v.strip()
               and len(v) <= 120 for v in values))
    demand(len(set(values)) == 3)


def read_db(path, expected):
    names_ok(expected)
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=4) as db:
        db.execute("PRAGMA query_only=ON")
        actual_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        demand({"group", "group_member", "user", "model", "access_grant",
                "config"}.issubset(actual_tables))
        group_rows = db.execute('SELECT id, name FROM "group"').fetchall()
        demand(len(group_rows) == 3 and
               {name for _id, name in group_rows} == set(expected.values()))
        gid = {role: next(group_id for group_id, name in group_rows
                          if name == expected[role]) for role in ROLES}
        members = {}
        roles = {}
        for role in ROLES:
            members[role] = {item[0] for item in db.execute(
                'SELECT user_id FROM "group_member" WHERE group_id=?',
                (gid[role],))}
            # Never print counts by identity or actual user identifiers.
            role_counts = dict(db.execute(
                'SELECT u.role, COUNT(*) FROM "group_member" gm '
                'JOIN "user" u ON gm.user_id=u.id '
                'WHERE gm.group_id=? GROUP BY u.role', (gid[role],)))
            roles[role] = {
                "USER": role_counts.get("user", 0),
                "PENDING": role_counts.get("pending", 0),
                "ADMIN": role_counts.get("admin", 0),
            }
            demand(sum(role_counts.values()) == len(members[role]))
            demand(set(role_counts).issubset({"user", "pending", "admin"}))
        overlap = bool(members["adults"] & members["children"])
        # No user IDs, names, emails or OIDC claims leave the guest.
        # OAuth fields are only used to count nonempty saved mappings;
        # their presence alone does NOT prove current SSO eligibility.
        user_columns = {row[1] for row in db.execute('PRAGMA table_info("user")')}
        demand({"id", "role", "oauth"}.issubset(user_columns))
        accounts = db.execute('SELECT role, oauth FROM "user"').fetchall()
        account_roles = {"user": 0, "pending": 0, "admin": 0}
        oauth_linked = 0
        for account_role, raw_oauth in accounts:
            demand(account_role in account_roles)
            account_roles[account_role] += 1
            if raw_oauth is not None:
                parsed = json.loads(raw_oauth) if isinstance(raw_oauth, str) else raw_oauth
                demand(parsed is None or isinstance(parsed, dict))
                oauth_linked += isinstance(parsed, dict) and bool(parsed)
        model_rows = db.execute(
            'SELECT id, base_model_id, is_active FROM "model"').fetchall()
        registered = {model_id: (base_id, bool(active)) for
                      model_id, base_id, active in model_rows}
        demand(len(registered) == len(model_rows))
        grants = db.execute(
            "SELECT resource_id, principal_type, principal_id, permission "
            "FROM access_grant WHERE resource_type='model'").fetchall()
        public_read = sum(1 for _id, p_type, p_id, perm in grants
                          if p_type == "user" and p_id == "*" and perm == "read")
        invalid_model_grants = sum(
            1 for model_id, p_type, p_id, perm in grants
            if model_id not in registered
            or p_type not in ("user", "group")
            or perm not in ("read", "write")
            or (p_type == "group" and p_id not in set(gid.values()))
        )
        child_grants = [model_id for model_id, p_type, principal, perm in grants
                        if p_type == "group"
                        and principal == gid["children"] and perm == "read"]
        adult_grants = [model_id for model_id, p_type, principal, perm in grants
                        if p_type == "group"
                        and principal == gid["adults"] and perm == "read"]
        raw_registered = {tag: tag in registered for tag in MODEL_TAGS}
        # Registered raw models granted to children can bypass role-specific
        # system prompts; aliases must not be treated as a security boundary.
        child_raw = sum(tag in child_grants for tag in MODEL_TAGS)
        invalid_child_public = bool(public_read or child_raw or overlap)
        statuses = {}
        for tag in MODEL_TAGS:
            aliases = [mid for mid, (base, active) in registered.items()
                       if base == tag and active]
            statuses[tag] = {
                "RAW_REGISTERED": raw_registered[tag],
                "ACTIVE_ALIASES": len(aliases),
                "ADULT_READ_ALIASES": sum(mid in adult_grants for mid in aliases),
                "CHILD_READ_ALIASES": sum(mid in child_grants for mid in aliases),
            }
        return {
            "STATUS": "REVIEW_REQUIRED" if (invalid_child_public or invalid_model_grants)
                      else "INVENTORY_ONLY",
            "TOTAL_REGISTERED_MODELS": len(registered),
            "TOTAL_MODEL_GRANTS": len(grants),
            "PUBLIC_READ_GRANTS": public_read,
            "UNKNOWN_OR_FOREIGN_MODEL_GRANTS": invalid_model_grants,
            "ADULT_CHILD_MEMBER_OVERLAP": "YES" if overlap else "NO",
            "ADULT_MEMBERS": len(members["adults"]),
            "CHILD_MEMBERS": len(members["children"]),
            "FAMILY_MEMBERS": len(members["family"]),
            "TOTAL_OPEN_WEBUI_ACCOUNTS": len(accounts),
            "ACCOUNT_ROLE_USER": account_roles["user"],
            "ACCOUNT_ROLE_PENDING": account_roles["pending"],
            "ACCOUNT_ROLE_ADMIN": account_roles["admin"],
            "OAUTH_LINKED_ACCOUNT_RECORDS": oauth_linked,
            "OIDC_GROUP_CLAIMS_VALIDATED": "NO",
            "ADULT_USER_ROLES": roles["adults"]["USER"],
            "ADULT_PENDING_ROLES": roles["adults"]["PENDING"],
            "CHILD_USER_ROLES": roles["children"]["USER"],
            "CHILD_PENDING_ROLES": roles["children"]["PENDING"],
            "CHILD_RAW_MODEL_READ_GRANTS": child_raw,
            "CATALOG_MODEL": statuses[MODEL_TAGS[0]],
            "MULTILINGUAL_MODEL": statuses[MODEL_TAGS[1]],
            "EMBEDDING_MODEL": statuses[MODEL_TAGS[2]],
            "GROUP_REVOCATION_E2E": "NOT_PROVEN",
            "MODEL_API_DENY_E2E": "NOT_PROVEN",
            "CHANGED": False,
            "AUDIT": "READ_ONLY",
        }


def run():
    try:
        args = json.load(sys.stdin)
        demand(isinstance(args, dict) and args.get("version") == "0.10.2")
        expected = args.get("expected")
        names_ok(expected)
        output = subprocess.check_output(
            ["podman", "inspect", "open-webui"], text=True,
            stderr=subprocess.DEVNULL, timeout=15)
        instances = json.loads(output)
        demand(isinstance(instances, list) and len(instances) == 1)
        mounts = [m.get("Source") for m in instances[0].get("Mounts", [])
                  if m.get("Destination") == "/app/backend/data"]
        demand(mounts == ["/srv/ai/open-webui"])
        env = instances[0].get("Config", {}).get("Env", [])
        demand(isinstance(env, list))
        envmap = dict(v.split("=", 1) for v in env
                      if isinstance(v, str) and "=" in v)
        demand(envmap.get("ENABLE_PERSISTENT_CONFIG", "True").lower() == "true")
        demand(envmap.get("BYPASS_MODEL_ACCESS_CONTROL", "False").lower() != "true")
        demand(not any(key in envmap for key in
                       ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")))
        file = Path(mounts[0]) / "webui.db"
        demand(file.is_file() and not file.is_symlink())
        result = read_db(file, expected)
        print(FRAME + json.dumps(result, sort_keys=True))
    except Exception:
        print(FRAME + '{"AUDIT":"FAILED_CLOSED","CHANGED":false}')
        raise SystemExit(2)


if __name__ == "__main__":
    run()
