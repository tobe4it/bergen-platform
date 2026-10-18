"""Token-free, read-only Open WebUI v0.10.2 family-group audit.

Reads JSON configuration exclusively from stdin, never command arguments.
Emits only fixed, non-identifying classifications. Never writes the database.
"""
import json
import pathlib
import sqlite3
import subprocess
import sys

ROLES = ("family", "adults", "children")
FLAGS = (
    ("WEB_SEARCH", "features", "web_search", "USER_PERMISSIONS_FEATURES_WEB_SEARCH", True),
    ("IMAGE_GENERATION", "features", "image_generation", "USER_PERMISSIONS_FEATURES_IMAGE_GENERATION", True),
    ("CODE_INTERPRETER", "features", "code_interpreter", "USER_PERMISSIONS_FEATURES_CODE_INTERPRETER", True),
    ("FILE_UPLOAD", "chat", "file_upload", "USER_PERMISSIONS_CHAT_FILE_UPLOAD", True),
    ("API_KEYS", "features", "api_keys", "USER_PERMISSIONS_FEATURES_API_KEYS", False),
    ("DIRECT_TOOLS", "features", "direct_tool_servers", "USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS", False),
    ("WORKSPACE_TOOLS", "workspace", "tools", "USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS", False),
)


class AuditError(Exception):
    pass


def require_expected(expected):
    if not isinstance(expected, dict) or set(expected) != set(ROLES):
        raise AuditError("Invalid expected role map")
    names = [expected[role] for role in ROLES]
    if any(not isinstance(n, str) or not n or n.strip() != n or len(n) > 120 for n in names):
        raise AuditError("Invalid group name")
    if len(set(names)) != 3:
        raise AuditError("Non-distinct group names")


def parse_object(value):
    if value is None:
        return {}
    obj = json.loads(value) if isinstance(value, str) else value
    if not isinstance(obj, dict):
        raise AuditError("Unexpected JSON shape")
    return obj


def bool_category(value):
    return "ON" if value is True else "OFF" if value is False else "UNVERIFIED"


def audit_db(dbpath, expected, environment):
    require_expected(expected)
    if not isinstance(environment, dict):
        raise AuditError("Malformed runtime metadata")
    persistent = environment.get("ENABLE_PERSISTENT_CONFIG", "True").lower() == "true"
    result = {"AUDIT": "READ_ONLY", "VERSION_REVIEWED": "V0_10_2",
              "PERSISTENT_CONFIG": bool_category(persistent)}
    uri = pathlib.Path(dbpath).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"group", "group_member", "access_grant", "user", "api_key", "config"}.issubset(tables):
            raise AuditError("Unreviewed database schema")
        group_rows = db.execute(
            'SELECT id, name, user_id, data, permissions FROM "group"'
        ).fetchall()
        if len(group_rows) > 1000:
            raise AuditError("Oversized group inventory")
        result["GROUP_COUNT"] = len(group_rows)
        result["OTHER_GROUPS_PRESENT"] = "YES" if len(group_rows) != 3 else "NO"
        result["API_KEY_COUNT"] = db.execute('SELECT COUNT(*) FROM "api_key"').fetchone()[0]
        result["TOTAL_MEMBERSHIPS"] = db.execute('SELECT COUNT(*) FROM "group_member"').fetchone()[0]
        result["PUBLIC_READ_GRANTS"] = db.execute(
            "SELECT COUNT(*) FROM access_grant WHERE principal_type='user' AND principal_id='*' AND permission='read'"
        ).fetchone()[0]
        all_present = len(group_rows) == 3
        for role in ROLES:
            label = role.upper()
            matches = [r for r in group_rows if r[1] == expected[role]]
            status = "PRESENT" if len(matches) == 1 else "MISSING" if not matches else "DUPLICATE"
            result[label] = status
            if status != "PRESENT":
                all_present = False
                continue
            gid, _, owner, raw_data, raw_perms = matches[0]
            data, permissions = parse_object(raw_data), parse_object(raw_perms)
            share = data.get("config", {})
            if not isinstance(share, dict):
                raise AuditError("Malformed share config")
            share = share.get("share")
            result[label + "_SHARE"] = (
                "NO_ONE" if share is False else
                "MEMBERS" if share == "members" else
                "ANYONE" if share is True else "UNVERIFIED"
            )
            result[label + "_OWNER_ADMIN"] = "YES" if db.execute(
                'SELECT COUNT(*) FROM "user" WHERE id=? AND role=?', (owner, "admin")
            ).fetchone()[0] == 1 else "NO"
            result[label + "_MEMBERS"] = db.execute(
                "SELECT COUNT(*) FROM group_member WHERE group_id=?", (gid,)
            ).fetchone()[0]
            result[label + "_RESOURCE_GRANTS"] = db.execute(
                "SELECT COUNT(*) FROM access_grant WHERE principal_type='group' AND principal_id=?", (gid,)
            ).fetchone()[0]
            result[label + "_PERMISSIONS"] = "STORED" if permissions else "EMPTY"
            for flag, section, key, _, _ in FLAGS:
                values = permissions.get(section, {})
                if not isinstance(values, dict):
                    raise AuditError("Malformed group permission")
                result[label + "_" + flag] = bool_category(values.get(key))
            if result[label + "_SHARE"] != "NO_ONE" or result[label + "_OWNER_ADMIN"] != "YES":
                all_present = False

        defaults = {}
        source = "ENV_DEFAULT"
        if persistent:
            config_row = db.execute(
                "SELECT value FROM config WHERE key='user.permissions'"
            ).fetchone()
            if config_row:
                defaults = parse_object(config_row[0])
                source = "DATABASE"
        result["DEFAULT_SOURCE"] = source
        for flag, section, key, envkey, fallback in FLAGS:
            data = defaults.get(section, {})
            if not isinstance(data, dict):
                raise AuditError("Malformed default permission")
            value = data.get(key)
            if value is None:
                raw = environment.get(envkey, str(fallback))
                if not isinstance(raw, str) or raw.lower() not in ("true", "false"):
                    raise AuditError("Malformed permission environment")
                value = raw.lower() == "true"
            result["DEFAULT_" + flag] = bool_category(value)

    result["STATUS"] = "INVENTORY_PRESENT_ONLY" if all_present else "MANUAL_REVIEW_REQUIRED"
    result["MEMBERSHIP_SEPARATION_PROVEN"] = "NO"
    result["RESOURCE_ACL_SEPARATION_PROVEN"] = "NO"
    result["REVOCATION_PROVEN"] = "NO"
    result["GROUPS_OR_PERMISSIONS_CHANGED"] = "NO"
    return result


def main():
    try:
        inputs = json.load(sys.stdin)
        if not isinstance(inputs, dict) or inputs.get("version") != "0.10.2":
            raise AuditError("Unsupported runtime version")
        expected = inputs.get("expected")
        require_expected(expected)
        inspect = json.loads(subprocess.check_output(
            ["podman", "inspect", "open-webui"], text=True,
            stderr=subprocess.DEVNULL, timeout=15
        ))
        if not isinstance(inspect, list) or len(inspect) != 1:
            raise AuditError("Unexpected container inventory")
        mounts = [
            m.get("Source") for m in inspect[0].get("Mounts", [])
            if m.get("Destination") == "/app/backend/data"
        ]
        if mounts != ["/srv/ai/open-webui"]:
            raise AuditError("Unexpected data mount")
        env_items = inspect[0].get("Config", {}).get("Env", [])
        if not isinstance(env_items, list):
            raise AuditError("Unexpected environment")
        env = dict(item.split("=", 1) for item in env_items if isinstance(item, str) and "=" in item)
        if any(key in env for key in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
            raise AuditError("External/overridden database not reviewed")
        dbpath = pathlib.Path(mounts[0]) / "webui.db"
        if not dbpath.is_file():
            raise AuditError("Database not found")
        print(json.dumps(audit_db(dbpath, expected, env), sort_keys=True))
    except Exception:
        # No exception details: they may contain private paths or identifiers.
        print('{"AUDIT":"FAILED_CLOSED"}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
