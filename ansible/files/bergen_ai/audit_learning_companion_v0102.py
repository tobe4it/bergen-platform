"""Open WebUI v0.10.2 child-learning feature/role audit, strictly SELECT-only.

All live site names enter over stdin; only stable role labels leave stdout.
This inventories actual DB-persisted settings. It does not test reminder
delivery, prompt deployment, child content controls, or effective resource ACLs.
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROLES = ("family", "adults", "children")
PERMS = {
    "MEMORIES": ("features", "memories"),
    "CALENDAR": ("features", "calendar"),
    "AUTOMATIONS": ("features", "automations"),
    "WEB_SEARCH": ("features", "web_search"),
    "IMAGE_GENERATION": ("features", "image_generation"),
    "CODE_INTERPRETER": ("features", "code_interpreter"),
    "FILE_UPLOAD": ("chat", "file_upload"),
    "WEB_UPLOAD": ("chat", "web_upload"),
    "CHAT_SHARING": ("chat", "share"),
    "PUBLIC_CALENDARS": ("sharing", "public_calendars"),
    "PUBLIC_CHATS": ("sharing", "public_chats"),
    "PUBLIC_NOTES": ("sharing", "public_notes"),
    "PUBLIC_TOOLS": ("sharing", "public_tools"),
    "API_KEYS": ("features", "api_keys"),
    "DIRECT_TOOL_SERVERS": ("features", "direct_tool_servers"),
    "USER_WEBHOOKS": ("features", "webhooks"),
}
CONTROLS = {
    "MEMORIES_ENABLED": "memories.enable",
    "MEMORIES_SYSTEM_CONTEXT": "memories.system_context.enable",
    "MEMORIES_BACKGROUND_REVIEW": "memories.background_review.enable",
    "CALENDAR_ENABLED": "calendar.enable",
    "AUTOMATIONS_ENABLED": "automations.enable",
    "USER_WEBHOOKS_ENABLED": "ui.enable_user_webhooks",
}


class Refuse(Exception):
    pass


def checked_mapping(raw):
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise Refuse("Unexpected JSON object")
    return value


def binary(value):
    return "ON" if value is True else "OFF" if value is False else "UNSET"


def flag(document, key):
    section, leaf = PERMS[key]
    nested = document.get(section, {})
    if not isinstance(nested, dict):
        raise Refuse("Unreviewed permission structure")
    value = nested.get(leaf)
    if value is not None and type(value) is not bool:
        raise Refuse("Invalid permission type")
    return value


def allow_if_member(global_perms, groups, permission, roles):
    """Simulate only group OR grants, not live access or delivery."""
    values = [flag(global_perms, permission)]
    values.extend(flag(groups[role], permission) for role in roles)
    if any(value is True for value in values):
        return "ON"
    if values[0] is None:
        return "UNVERIFIED"
    return "OFF"


def require_expected(mapping):
    if not isinstance(mapping, dict) or set(mapping) != set(ROLES):
        raise Refuse("Unexpected group map")
    names = [mapping[role] for role in ROLES]
    if any(not isinstance(name, str) or not name or name != name.strip()
           or len(name) > 120 for name in names):
        raise Refuse("Invalid site group mapping")
    if len(set(names)) != len(names):
        raise Refuse("Duplicate group mapping")


def audit_db(path, expected):
    require_expected(expected)
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not {"group", "group_member", "config", "access_grant"}.issubset(tables):
            raise Refuse("Unreviewed application schema")
        groups = db.execute('SELECT id, name, data, permissions FROM "group"').fetchall()
        if len(groups) != 3 or {r[1] for r in groups} != set(expected.values()):
            raise Refuse("Family group inventory drifted")
        member_count = db.execute('SELECT COUNT(*) FROM "group_member"').fetchone()[0]
        if member_count != 0:
            raise Refuse("Membership already present; do not infer baseline")
        role_perms = {}
        for role in ROLES:
            matches = [row for row in groups if row[1] == expected[role]]
            if len(matches) != 1:
                raise Refuse("Duplicated role")
            _, _, raw_data, raw_perms = matches[0]
            data = checked_mapping(raw_data or "{}")
            sharing = data.get("config", {})
            if not isinstance(sharing, dict) or sharing.get("share") is not False:
                raise Refuse("Expected private group share policy")
            role_perms[role] = checked_mapping(raw_perms or "{}")

        config = dict(db.execute("SELECT key,value FROM config"))
        if "user.permissions" not in config:
            raise Refuse("No persisted default permissions")
        global_perms = checked_mapping(config["user.permissions"])
        for must in ("workspace", "sharing", "features", "chat",
                     "access_grants", "settings"):
            if not isinstance(global_perms.get(must), dict):
                raise Refuse("Unexpected default permissions")
        out = {
            "AUDIT": "READ_ONLY",
            "STATUS": "POLICY_INVENTORY_ONLY",
            "VERSION_REVIEWED": "V0_10_2",
            "PERSISTENT_CONFIG": "ON",
            "DEFAULT_SOURCE": "DATABASE",
            "GROUP_COUNT": 3,
            "TOTAL_MEMBERSHIPS": member_count,
            "NO_MEMBERSHIP_WRITES": "YES",
            "MEMORY_ISOLATION_E2E": "NOT_PROVEN",
            "REMINDER_DELIVERY_E2E": "NOT_PROVEN",
            "HOMEWORK_BEHAVIOR_E2E": "NOT_PROVEN",
            "RESOURCE_ACL_SEPARATION_E2E": "NOT_PROVEN",
        }
        for name in PERMS:
            out["GLOBAL_" + name] = binary(flag(global_perms, name))
            for role in ROLES:
                out[role.upper() + "_" + name] = binary(flag(role_perms[role], name))
        for name, config_key in CONTROLS.items():
            if config_key not in config:
                out[name] = "UNSET"
            else:
                raw = json.loads(config[config_key])
                if type(raw) is not bool:
                    raise Refuse("Unexpected scheduler/memory setting")
                out[name] = binary(raw)

        for key in ("MEMORIES", "CALENDAR", "AUTOMATIONS", "WEB_SEARCH",
                    "IMAGE_GENERATION", "CODE_INTERPRETER", "FILE_UPLOAD",
                    "WEB_UPLOAD", "CHAT_SHARING", "PUBLIC_CALENDARS",
                    "PUBLIC_CHATS", "USER_WEBHOOKS"):
            out["CHILD_IF_ASSIGNED_" + key] = allow_if_member(
                global_perms, role_perms, key, ("family", "children")
            )
            out["ADULT_IF_ASSIGNED_" + key] = allow_if_member(
                global_perms, role_perms, key, ("family", "adults")
            )
        return out


def main():
    try:
        inp = json.load(sys.stdin)
        if not isinstance(inp, dict) or inp.get("version") != "0.10.2":
            raise Refuse("Unreviewed application version")
        expected = inp.get("expected")
        require_expected(expected)
        inspect = json.loads(subprocess.check_output(
            ["podman", "inspect", "open-webui"], text=True,
            stderr=subprocess.DEVNULL, timeout=15
        ))
        if not isinstance(inspect, list) or len(inspect) != 1:
            raise Refuse("Unexpected container")
        mounts = [m.get("Source") for m in inspect[0].get("Mounts", [])
                  if m.get("Destination") == "/app/backend/data"]
        if mounts != ["/srv/ai/open-webui"]:
            raise Refuse("Unexpected data mount")
        env_items = inspect[0].get("Config", {}).get("Env")
        if not isinstance(env_items, list):
            raise Refuse("Unexpected runtime environment")
        env = dict(item.split("=", 1) for item in env_items
                   if isinstance(item, str) and "=" in item)
        if env.get("ENABLE_PERSISTENT_CONFIG", "True").lower() != "true":
            raise Refuse("Persisted configuration disabled")
        if any(key in env for key in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
            raise Refuse("Unreviewed backend")
        path = Path(mounts[0]) / "webui.db"
        if not path.is_file():
            raise Refuse("Missing database")
        print(json.dumps(audit_db(path, expected), sort_keys=True))
    except Exception:
        print('{"AUDIT":"FAILED_CLOSED"}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
