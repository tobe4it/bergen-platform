"""Version-pinned, read-only failed-apply classifier for Open WebUI v0.10.2.

No raw traceback, config JSON, personal IDs, group names or container
environment is returned. The Open WebUI ORM probe performs only Config.get.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys

APP_PROBE = r"""
import asyncio
import hashlib
import json
import sys

try:
    from open_webui.config import Config
except Exception:
    print("PROBE=IMPORT_FAILED")
    raise SystemExit(2)

async def main():
    try:
        if not Config.persistent_enabled_for("user.permissions"):
            print("PROBE=PERSISTENCE_DISABLED")
            raise SystemExit(2)
        value = await Config.get("user.permissions")
        if not isinstance(value, dict):
            print("PROBE=CONFIG_INVALID")
            raise SystemExit(2)
        sha = hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        if sha != json.load(sys.stdin).get("expected_sha256"):
            print("PROBE=CONFIG_MISMATCH")
            raise SystemExit(2)
        print("PROBE=READ_CONFIRMED")
    except SystemExit:
        raise
    except Exception:
        print("PROBE=DATABASE_READ_FAILED")
        raise SystemExit(2)

asyncio.run(main())
"""


class AuditError(Exception):
    pass


def sha256(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def check_backup(sha):
    path = Path("/var/lib/bergen-platform/open-webui") / (
        "default-user-permissions-" + sha + ".json"
    )
    if not path.exists() and not path.is_symlink():
        return "NOT_FOUND"
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or (st.st_mode & 0o077):
            return "UNSAFE"
        record = json.loads(path.read_text())
        before = record.get("before")
        if not isinstance(before, dict):
            return "INVALID"
        if record.get("version") != "0.10.2":
            return "INVALID"
        if record.get("before_sha") != sha or sha256(before) != sha:
            return "INVALID"
        return "VERIFIED"
    except Exception:
        return "UNREADABLE"


def probe_app(current_sha):
    try:
        result = subprocess.run(
            ["podman", "exec", "-i", "open-webui", "python3", "-c", APP_PROBE],
            input=json.dumps({"expected_sha256": current_sha}),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception:
        return "EXEC_FAILED"

    accepted = {
        "IMPORT_FAILED", "PERSISTENCE_DISABLED", "CONFIG_INVALID",
        "CONFIG_MISMATCH", "READ_CONFIRMED", "DATABASE_READ_FAILED"
    }
    # Application may emit startup logs to stdout. Whitelist only exact markers.
    found = [
        line.removeprefix("PROBE=")
        for line in result.stdout.splitlines()
        if line.startswith("PROBE=") and line.removeprefix("PROBE=") in accepted
    ]
    if len(found) != 1:
        return "UNCLASSIFIED_FAILURE"
    if (result.returncode == 0) != (found[0] == "READ_CONFIRMED"):
        return "UNCLASSIFIED_FAILURE"
    return found[0]


def audit(req):
    if not isinstance(req, dict) or req.get("version") != "0.10.2":
        raise AuditError("Unreviewed version")
    former_sha = req.get("previous_sha256")
    if not isinstance(former_sha, str) or len(former_sha) != 64 or any(
        x not in "0123456789abcdef" for x in former_sha
    ):
        raise AuditError("Invalid previous fingerprint")
    inspect = json.loads(subprocess.check_output(
        ["podman", "inspect", "open-webui"], text=True,
        stderr=subprocess.DEVNULL, timeout=15
    ))
    if not isinstance(inspect, list) or len(inspect) != 1:
        raise AuditError("Unexpected container")
    mounts = [m.get("Source") for m in inspect[0].get("Mounts", [])
              if m.get("Destination") == "/app/backend/data"]
    if mounts != ["/srv/ai/open-webui"]:
        raise AuditError("Unknown database layout")
    envs = inspect[0].get("Config", {}).get("Env") or []
    environment = dict(i.split("=", 1) for i in envs if isinstance(i, str) and "=" in i)
    if environment.get("ENABLE_PERSISTENT_CONFIG", "True").lower() != "true":
        raise AuditError("Persistence disabled")
    if any(key in environment for key in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
        raise AuditError("Overridden database layout")
    db = Path(mounts[0]) / "webui.db"
    if not db.is_file():
        raise AuditError("Database absent")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as con:
        con.execute("PRAGMA query_only=ON")
        row = con.execute("SELECT value FROM config WHERE key='user.permissions'").fetchone()
        if not row:
            raise AuditError("Missing persisted permissions")
        value = json.loads(row[0])
        if not isinstance(value, dict):
            raise AuditError("Malformed persisted settings")
    current_sha = sha256(value)
    return {
        "STATUS": "DIAGNOSTIC_COMPLETE",
        "CHANGED": False,
        "STATE": "UNCHANGED" if current_sha == former_sha else "DIFFERENT",
        "CURRENT_SHA256": current_sha,
        "BACKUP_FOR_PREVIOUS_STATE": check_backup(former_sha),
        "APP_ORM_READ": probe_app(current_sha),
        "AUDIT": "READ_ONLY",
    }


if __name__ == "__main__":
    try:
        result = audit(json.load(sys.stdin))
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print('{"STATUS":"FAILED_CLOSED","CHANGED":false,"AUDIT":"READ_ONLY"}')
        raise SystemExit(2)
