"""Controlled Open WebUI v0.10.2 global user-permission baseline.

Host-side SQLite is SELECT-only. Production writes are performed exclusively
through the *installed application's* Config.upsert ORM method, in its own
container. This is version-pinned; review again before an application upgrade.

Input: JSON via stdin. Output: sanitized JSON status categories only.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

FLAGS = (("features", "web_search"),
         ("features", "image_generation"),
         ("features", "code_interpreter"),
         ("chat", "file_upload"))
ROLES = ("family", "adults", "children")
BACKUP_DIR = Path("/var/lib/bergen-platform/open-webui")

# Executed in the installed Open WebUI container. We invoke the same
# application-layer Config.upsert used by the admin default-permissions route.
# No direct SQL writes and no API keys or OAuth credentials.
APP_WRITER = r"""
import asyncio
import json
import os
from pathlib import Path
import sys

def initialize_existing_secret():
    # start.sh makes the key available to the uvicorn process, not
    # necessarily to separate podman exec processes. Reuse the key
    # file in memory without exposing its contents in args or logs.
    if os.getenv("WEBUI_SECRET_KEY") or os.getenv("WEBUI_JWT_SECRET_KEY"):
        return
    name = os.getenv("WEBUI_SECRET_KEY_FILE", ".webui_secret_key")
    path = Path(name)
    if not path.is_absolute():
        path = Path("/app/backend") / path
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Existing WebUI key file unavailable")
    existing = path.read_text().strip()
    if not existing:
        raise RuntimeError("Existing WebUI key file empty")
    os.environ["WEBUI_SECRET_KEY"] = existing

initialize_existing_secret()
from open_webui.models.config import Config
# Import only the config storage model, not open_webui.config:
# the latter runs migrations and copies static assets on import.
Config.configure(defaults={}, enable_persistent=True, enable_oauth_persistent=False)

async def main():
    request = json.load(sys.stdin)
    if request.get("mode") != "upsert_user_permissions_v0_10_2":
        raise RuntimeError("Refusing unexpected application action")
    before, after = request["before"], request["after"]
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise RuntimeError("Invalid permission payload")
    live = await Config.get("user.permissions")
    if live != before:
        raise RuntimeError("Concurrent default-permission change")
    if not Config.persistent_enabled_for("user.permissions"):
        raise RuntimeError("Runtime is not using persisted config")
    await Config.upsert({"user.permissions": after})
    confirmed = await Config.get("user.permissions")
    if confirmed != after:
        raise RuntimeError("Post-write application confirmation failed")
    print("APP_CONFIG_UPSERT=CONFIRMED")

asyncio.run(main())
"""


class GateError(Exception):
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_roles(expected):
    if not isinstance(expected, dict) or set(expected) != set(ROLES):
        raise GateError("Invalid role map")
    names = [expected[role] for role in ROLES]
    if any(not isinstance(name, str) or not name or name != name.strip()
           for name in names) or len(set(names)) != 3:
        raise GateError("Invalid site group names")


def parse_permissions(raw):
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise GateError("Unexpected permission JSON")
    if not {"workspace", "sharing", "access_grants", "chat",
            "features", "settings"}.issubset(value):
        raise GateError("Unexpected permissions schema")
    for section, key in FLAGS:
        if not isinstance(value.get(section), dict) or type(value[section].get(key)) is not bool:
            raise GateError("Missing or invalid permission flag")
    return value


def target_permissions(current):
    target = copy.deepcopy(parse_permissions(current))
    for section, key in FLAGS:
        target[section][key] = False
    return target


def read_runtime():
    response = json.loads(subprocess.check_output(
        ["podman", "inspect", "open-webui"],
        text=True, stderr=subprocess.DEVNULL, timeout=15
    ))
    if not isinstance(response, list) or len(response) != 1:
        raise GateError("Unexpected container inventory")
    container = response[0]
    mounts = [m.get("Source") for m in container.get("Mounts", [])
              if m.get("Destination") == "/app/backend/data"]
    if mounts != ["/srv/ai/open-webui"]:
        raise GateError("Unexpected data mount")
    items = container.get("Config", {}).get("Env") or []
    if not isinstance(items, list):
        raise GateError("Unexpected environment")
    env = dict(item.split("=", 1) for item in items if isinstance(item, str) and "=" in item)
    if env.get("ENABLE_PERSISTENT_CONFIG", "True").lower() != "true":
        raise GateError("Persistent config is not effective")
    if any(key in env for key in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
        raise GateError("Unexpected external/overridden database")
    return Path(mounts[0]) / "webui.db"


def read_db(dbpath, expected):
    validate_roles(expected)
    if not dbpath.is_file():
        raise GateError("Database unavailable")
    with sqlite3.connect(dbpath.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not {"config", "group", "group_member", "access_grant"}.issubset(tables):
            raise GateError("Unreviewed schema")
        group_rows = db.execute('SELECT name, data FROM "group"').fetchall()
        if len(group_rows) != 3 or {name for name, _ in group_rows} != set(expected.values()):
            raise GateError("Expected family groups have drifted")
        for _, raw_data in group_rows:
            data = json.loads(raw_data or "{}")
            if not isinstance(data, dict) or not isinstance(data.get("config"), dict):
                raise GateError("Malformed group share policy")
            if data["config"].get("share") is not False:
                raise GateError("Group share policy is not restricted")
        if db.execute('SELECT COUNT(*) FROM "group_member"').fetchone()[0] != 0:
            raise GateError("Membership has started; no baseline change allowed")
        row = db.execute(
            "SELECT value FROM config WHERE key='user.permissions'"
        ).fetchone()
        if not row:
            raise GateError("Persisted user.permissions missing")
        return parse_permissions(row[0])


def backup_file(before_sha):
    return BACKUP_DIR / ("default-user-permissions-" + before_sha + ".json")


def ensure_root():
    if os.geteuid() != 0:
        raise GateError("Root-only backup requires privilege")


def save_backup(before, after):
    ensure_root()
    BACKUP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Do not follow a replaced directory or an existing symlink.
    st = BACKUP_DIR.lstat()
    if not BACKUP_DIR.is_dir() or st.st_uid != os.geteuid() or (st.st_mode & 0o077):
        raise GateError("Unsafe backup directory permissions")
    before_sha = digest(before)
    record = {"version": "0.10.2", "before": before, "after": after,
              "before_sha": before_sha, "after_sha": digest(after)}
    path = backup_file(before_sha)
    if path.exists() or path.is_symlink():
        current = path.lstat()
        if not path.is_file() or current.st_uid != os.geteuid() or current.st_mode & 0o077:
            raise GateError("Unsafe existing backup")
        existing = json.loads(path.read_text())
        if existing != record:
            raise GateError("Existing backup mismatch")
        return path
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(record, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    return path


def load_backup(before_sha):
    ensure_root()
    if not isinstance(before_sha, str) or len(before_sha) != 64 or any(
        c not in "0123456789abcdef" for c in before_sha
    ):
        raise GateError("Invalid rollback selector")
    path = backup_file(before_sha)
    st = path.lstat()
    if not path.is_file() or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise GateError("Unsafe rollback backup")
    record = json.loads(path.read_text())
    if record.get("version") != "0.10.2" or record.get("before_sha") != before_sha:
        raise GateError("Backup version/hash mismatch")
    before = parse_permissions(record.get("before"))
    after = parse_permissions(record.get("after"))
    if digest(before) != before_sha or digest(after) != record.get("after_sha"):
        raise GateError("Backup integrity mismatch")
    if target_permissions(before) != after:
        raise GateError("Backup contains unexpected changes")
    return before, after


def app_upsert(before, after):
    result = subprocess.run(
        ["podman", "exec", "-i", "open-webui", "python3", "-c", APP_WRITER],
        input=json.dumps({
            "mode": "upsert_user_permissions_v0_10_2",
            "before": before, "after": after
        }), text=True, capture_output=True, timeout=90, check=False,
    )
    # Never print the application traceback: it might contain site secrets.
    if result.returncode != 0 or "APP_CONFIG_UPSERT=CONFIRMED" not in result.stdout:
        raise GateError("Application Config.upsert unsuccessful")


def require_sha(expected, actual):
    if not isinstance(expected, str) or expected != actual:
        raise GateError("Expected configuration fingerprint does not match")


def execute(req):
    if not isinstance(req, dict) or req.get("version") != "0.10.2":
        raise GateError("Unreviewed application version")
    action = req.get("action")
    if action not in ("audit", "apply", "rollback"):
        raise GateError("Unrecognized action")
    current = read_db(read_runtime(), req.get("expected"))
    current_sha = digest(current)
    desired = target_permissions(current)
    if action == "audit":
        return {"STATUS": "BASELINE_READY" if current != desired else "BASELINE_ALREADY_RESTRICTED",
                "CHANGED": False,
                "CURRENT_SHA256": current_sha,
                "TARGET_SHA256": digest(desired),
                "PERSISTENT_CONFIG": "ON",
                "STORAGE": "DATABASE",
                "MEMBERSHIPS": 0,
                "DEFAULT_WEB_SEARCH": "ON" if current["features"]["web_search"] else "OFF",
                "DEFAULT_IMAGE_GENERATION": "ON" if current["features"]["image_generation"] else "OFF",
                "DEFAULT_CODE_INTERPRETER": "ON" if current["features"]["code_interpreter"] else "OFF",
                "DEFAULT_FILE_UPLOAD": "ON" if current["chat"]["file_upload"] else "OFF"}
    if req.get("approved") is not True:
        raise GateError("Explicit operator approval required")
    require_sha(req.get("expected_sha256"), current_sha)
    if action == "apply":
        if current == desired:
            return {"STATUS": "ALREADY_COMPLIANT", "CHANGED": False,
                    "CONFIG_SHA256": current_sha}
        backup = save_backup(current, desired)
        app_upsert(current, desired)
        confirmed = read_db(read_runtime(), req["expected"])
        if confirmed != desired:
            raise GateError("Post-change drift; do not continue")
        return {"STATUS": "BASELINE_APPLIED", "CHANGED": True,
                "CONFIG_SHA256": digest(confirmed),
                "ROLLBACK_SELECTOR": digest(current),
                "BACKUP_STORED": "YES"}
    selector = req.get("rollback_selector")
    before, after = load_backup(selector)
    if current != after:
        raise GateError("Rollback refused because post-apply state has drifted")
    app_upsert(after, before)
    confirmed = read_db(read_runtime(), req["expected"])
    if confirmed != before:
        raise GateError("Rollback verification failed")
    return {"STATUS": "BASELINE_ROLLED_BACK", "CHANGED": True,
            "CONFIG_SHA256": digest(confirmed)}


def main():
    try:
        req = json.load(sys.stdin)
        print(json.dumps(execute(req), sort_keys=True))
    except Exception:
        # No exception details or raw config data in Ansible/GitHub logs.
        print('{"STATUS":"FAILED_CLOSED","CHANGED":false}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
