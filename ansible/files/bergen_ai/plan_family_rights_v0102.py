"""Read-only, version-pinned preflight for Bergen-AI family/child privileges.

Simulates explicit global and family/children group changes only. The audit
is not an apply and does not persist, grant membership or use API tokens.
"""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROLES = ("family", "adults", "children")
BASELINE_FALSE = (
    ("features", "web_search"), ("features", "image_generation"),
    ("features", "code_interpreter"), ("chat", "file_upload"),
)
DEFAULT_TO_FALSE = (
    ("features", "memories"), ("features", "calendar"),
    ("chat", "web_upload"), ("chat", "share"),
)
FAMILY_CHILD_FALSE = (
    *BASELINE_FALSE,
    ("chat", "web_upload"), ("chat", "share"),
    ("features", "automations"), ("features", "api_keys"),
    ("features", "direct_tool_servers"), ("features", "webhooks"),
    ("sharing", "public_calendars"), ("sharing", "public_chats"),
    ("sharing", "public_notes"), ("sharing", "public_tools"),
    ("sharing", "public_models"), ("sharing", "public_knowledge"),
    ("sharing", "public_prompts"), ("sharing", "public_skills"),
)
FAMILY_CHILD_TRUE = (("features", "memories"), ("features", "calendar"))
# Policy review remains necessary for functionality not explicitly handled.
ALLOWED_STORED_TRUE = {
    "features.memories", "features.calendar",
    "features.folders", "features.notes",
    "chat.delete", "chat.delete_message", "chat.continue_response",
    "chat.regenerate_response", "chat.rate_response", "chat.edit",
    "chat.stt", "chat.tts", "chat.call", "chat.temporary",
    "settings.interface",
}

class GateError(Exception):
    pass


def require_expected(mapping):
    if not isinstance(mapping, dict) or set(mapping) != set(ROLES):
        raise GateError("Invalid site role map")
    names = [mapping[role] for role in ROLES]
    if any(not isinstance(name, str) or not name or name != name.strip()
           or len(name) > 120 for name in names) or len(set(names)) != 3:
        raise GateError("Invalid names")


def parse(raw):
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise GateError("Malformed permission mapping")
    return data


def sha(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def read_flag(data, section, leaf):
    nested = data.get(section, {})
    if not isinstance(nested, dict):
        raise GateError("Unexpected permission section")
    v = nested.get(leaf)
    if v is not None and type(v) is not bool:
        raise GateError("Unexpected permission value")
    return v


def write_flag(data, section, leaf, value):
    data.setdefault(section, {})
    if not isinstance(data[section], dict):
        raise GateError("Unexpected permission section")
    before = data[section].get(leaf)
    if before is not None and type(before) is not bool:
        raise GateError("Unexpected permission value")
    data[section][leaf] = value


def effective(data, other, flags):
    return all(
        read_flag(data, sec, key) is True or
        read_flag(other["family"], sec, key) is True or
        read_flag(other["children"], sec, key) is True
        for sec, key in flags
    )


def all_off(data, group, flags):
    return all(not any(read_flag(doc, sec, key) is True for doc in
                       (data, group["family"], group["children"]))
               for sec, key in flags)


def unexpected_group_grants(group):
    count = 0
    by_category = {}
    for role in ("family", "children"):
        for section, fields in group[role].items():
            if not isinstance(fields, dict):
                raise GateError("Unreviewed group permissions schema")
            for name, value in fields.items():
                if type(value) is not bool:
                    raise GateError("Unreviewed group permission value")
                if value and f"{section}.{name}" not in ALLOWED_STORED_TRUE:
                    count += 1
                    by_category[section] = by_category.get(section, 0) + 1
    return count, by_category


def audit(path, expected):
    require_expected(expected)
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not {"group", "group_member", "access_grant", "config", "user"}.issubset(tables):
            raise GateError("Unreviewed SQLite schema")
        rows = db.execute(
            'SELECT id,name,user_id,data,permissions FROM "group"'
        ).fetchall()
        if len(rows) != 3 or {r[1] for r in rows} != set(expected.values()):
            raise GateError("Unexpected group inventory")
        if db.execute('SELECT COUNT(*) FROM "group_member"').fetchone()[0] != 0:
            raise GateError("Group members present")
        mapping = {}
        for role in ROLES:
            matches = [r for r in rows if r[1] == expected[role]]
            if len(matches) != 1:
                raise GateError("Duplicate group")
            gid, _, owner, raw_data, raw_perms = matches[0]
            data = parse(raw_data or "{}")
            config = data.get("config")
            if not isinstance(config, dict) or config.get("share") is not False:
                raise GateError("Share policy not private")
            if db.execute('SELECT COUNT(*) FROM "user" WHERE id=? AND role=?',
                          (owner, "admin")).fetchone()[0] != 1:
                raise GateError("Group owner not an administrator")
            if db.execute(
                "SELECT COUNT(*) FROM access_grant "
                "WHERE principal_type='group' AND principal_id=?", (gid,)
            ).fetchone()[0]:
                raise GateError("Group resource grants already exist")
            mapping[role] = parse(raw_perms or "{}")
        row = db.execute(
            "SELECT value FROM config WHERE key='user.permissions'"
        ).fetchone()
        if row is None:
            raise GateError("Missing persisted defaults")
        defaults = parse(row[0])
        for name in ("features", "chat", "sharing", "workspace", "access_grants", "settings"):
            if not isinstance(defaults.get(name), dict):
                raise GateError("Unknown defaults schema")
        if not all(read_flag(defaults, sec, key) is False
                   for sec, key in BASELINE_FALSE):
            raise GateError("Four-flag approved baseline no longer enforced")
    current = {"defaults": defaults, "family": mapping["family"],
               "adults": mapping["adults"], "children": mapping["children"]}
    proposal = copy.deepcopy(current)
    for sec, name in DEFAULT_TO_FALSE:
        write_flag(proposal["defaults"], sec, name, False)
    for role in ("family", "children"):
        for sec, name in FAMILY_CHILD_FALSE:
            write_flag(proposal[role], sec, name, False)
        for sec, name in FAMILY_CHILD_TRUE:
            write_flag(proposal[role], sec, name, True)
    group = {"family": proposal["family"], "children": proposal["children"]}
    target_features = ("web_search", "image_generation", "code_interpreter")
    target_off = (
        *FAMILY_CHILD_FALSE, ("chat", "web_upload"), ("chat", "share")
    )
    if not effective(proposal["defaults"], group, FAMILY_CHILD_TRUE):
        raise GateError("Learning features lost in plan")
    if not all_off(proposal["defaults"], group, target_off):
        raise GateError("Safety flags remain granted by target")
    extra, sections = unexpected_group_grants(group)
    result = {
        "STATUS": "NEEDS_POLICY_REVIEW" if extra else "READY_FOR_SEPARATE_APPROVAL",
        "AUDIT": "READ_ONLY",
        "CHANGED": False,
        "VERSION": "V0_10_2",
        "CURRENT_BUNDLE_SHA256": sha(current),
        "TARGET_BUNDLE_SHA256": sha(proposal),
        "CURRENT_GLOBAL_SHA256": sha(defaults),
        "TARGET_GLOBAL_SHA256": sha(proposal["defaults"]),
        "TARGET_CHILD_MEMORIES": "ON",
        "TARGET_CHILD_CALENDAR": "ON",
        "TARGET_CHILD_AUTOMATIONS": "OFF",
        "TARGET_CHILD_WEB_SEARCH": "OFF",
        "TARGET_CHILD_IMAGE_GENERATION": "OFF",
        "TARGET_CHILD_CODE_INTERPRETER": "OFF",
        "TARGET_CHILD_FILE_UPLOAD": "OFF",
        "TARGET_CHILD_WEB_UPLOAD": "OFF",
        "TARGET_CHILD_CHAT_SHARING": "OFF",
        "CURRENT_GLOBAL_WEB_UPLOAD": "ON" if read_flag(defaults, "chat", "web_upload") else "OFF",
        "CURRENT_GLOBAL_CHAT_SHARING": "ON" if read_flag(defaults, "chat", "share") else "OFF",
        "CURRENT_GLOBAL_MEMORIES": "ON" if read_flag(defaults, "features", "memories") else "OFF",
        "CURRENT_GLOBAL_CALENDAR": "ON" if read_flag(defaults, "features", "calendar") else "OFF",
        "REMAINING_UNREVIEWED_GROUP_TRUE": extra,
        "REMAINING_UNREVIEWED_WORKSPACE_TRUE": sections.get("workspace", 0),
        "REMAINING_UNREVIEWED_SHARING_TRUE": sections.get("sharing", 0),
        "REMAINING_UNREVIEWED_FEATURES_TRUE": sections.get("features", 0),
        "REMAINING_UNREVIEWED_CHAT_TRUE": sections.get("chat", 0),
        "REMAINING_UNREVIEWED_ACCESS_GRANTS_TRUE": sections.get("access_grants", 0),
        "REMAINING_UNREVIEWED_OTHER_TRUE": sum(
            val for key, val in sections.items() if key not in
            {"workspace", "sharing", "features", "chat", "access_grants"}
        ),
        "NO_MEMBERSHIPS_CHANGED": "YES",
        "NO_PERSISTED_RIGHTS_CHANGED": "YES",
        "USER_E2E": "NOT_TESTED",
        "CHILD_MEMORY_E2E": "NOT_TESTED",
        "CALENDAR_DELIVERY_E2E": "NOT_TESTED",
    }
    return result


def main():
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("version") != "0.10.2":
            raise GateError("Unsupported version")
        expected = request.get("expected")
        require_expected(expected)
        obj = json.loads(subprocess.check_output(
            ["podman", "inspect", "open-webui"], text=True,
            stderr=subprocess.DEVNULL, timeout=15
        ))
        if not isinstance(obj, list) or len(obj) != 1:
            raise GateError("Unknown runtime container")
        container = obj[0]
        mounts = [m.get("Source") for m in container.get("Mounts", [])
                  if m.get("Destination") == "/app/backend/data"]
        if mounts != ["/srv/ai/open-webui"]:
            raise GateError("Unknown storage layout")
        env_raw = container.get("Config", {}).get("Env")
        if not isinstance(env_raw, list):
            raise GateError("Unexpected environment")
        env = dict(item.split("=", 1) for item in env_raw
                   if isinstance(item, str) and "=" in item)
        if env.get("ENABLE_PERSISTENT_CONFIG", "True").lower() != "true":
            raise GateError("Persistent configuration disabled")
        if any(k in env for k in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
            raise GateError("Unexpected external DB")
        path = Path(mounts[0]) / "webui.db"
        if not path.is_file():
            raise GateError("Database absent")
        print(json.dumps(audit(path, expected), sort_keys=True))
    except Exception:
        print('{"STATUS":"FAILED_CLOSED","AUDIT":"READ_ONLY"}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
