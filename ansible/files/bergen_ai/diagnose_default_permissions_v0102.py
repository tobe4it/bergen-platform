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
import os
import sys

ERROR_CLASSES = {
    "ModuleNotFoundError", "ImportError", "PermissionError",
    "OperationalError", "RuntimeError", "AttributeError",
    "TypeError", "ValueError", "KeyError", "OSError",
    "SystemExit", "FileNotFoundError", "AssertionError",
}

def mark(value):
    print("PROBE=" + value, flush=True)

def safe_error(exc):
    name = type(exc).__name__
    print("PROBE_ERROR=" + (name if name in ERROR_CLASSES else "OTHER"), flush=True)

mark("PYTHON_STARTED")
mark("BACKEND_PACKAGE_PRESENT" if os.path.isdir("/app/backend/open_webui") else "BACKEND_PACKAGE_MISSING")
try:
    from open_webui.config import Config
except BaseException as exc:
    safe_error(exc)
    mark("IMPORT_FAILED")
    raise SystemExit(2)

mark("IMPORT_OK")

async def main():
    try:
        if not Config.persistent_enabled_for("user.permissions"):
            mark("PERSISTENCE_DISABLED")
            raise SystemExit(2)
        value = await Config.get("user.permissions")
        if not isinstance(value, dict):
            mark("CONFIG_INVALID")
            raise SystemExit(2)
        sha = hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        if sha != json.load(sys.stdin).get("expected_sha256"):
            mark("CONFIG_MISMATCH")
            raise SystemExit(2)
        mark("READ_CONFIRMED")
    except SystemExit:
        raise
    except BaseException as exc:
        safe_error(exc)
        mark("DATABASE_READ_FAILED")
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


def classify_stderr(stderr):
    """Fixed categories only; never return any excerpt of a traceback."""
    text = stderr.lower()
    if "no such container" in text or "container not found" in text:
        return "CONTAINER_NOT_FOUND"
    if "permission denied" in text:
        return "PERMISSION_DENIED"
    if "executable file not found" in text or "executable not found" in text:
        return "PYTHON_BINARY_NOT_FOUND"
    if "modulenotfounderror" in text:
        return "MODULE_NOT_FOUND"
    if "importerror" in text:
        return "IMPORT_ERROR"
    if "operationalerror" in text:
        return "DATABASE_ERROR"
    if "traceback" in text:
        return "PYTHON_EXCEPTION"
    if text.strip():
        return "OTHER_ERROR"
    return "NONE"


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
        return {"APP_ORM_READ": "TIMEOUT", "APP_STAGE": "PROCESS_TIMEOUT",
                "APP_ERROR_CLASS": "NONE", "APP_STDERR_CLASS": "NONE"}
    except Exception:
        return {"APP_ORM_READ": "EXEC_FAILED", "APP_STAGE": "PROCESS_LAUNCH_FAILED",
                "APP_ERROR_CLASS": "NONE", "APP_STDERR_CLASS": "NONE"}

    # Whitelist only exact stage markers and known Python exception class names.
    stages = {
        "PYTHON_STARTED", "BACKEND_PACKAGE_PRESENT", "BACKEND_PACKAGE_MISSING",
        "IMPORT_OK", "IMPORT_FAILED", "PERSISTENCE_DISABLED", "CONFIG_INVALID",
        "CONFIG_MISMATCH", "READ_CONFIRMED", "DATABASE_READ_FAILED",
    }
    error_classes = {
        "ModuleNotFoundError", "ImportError", "PermissionError",
        "OperationalError", "RuntimeError", "AttributeError",
        "TypeError", "ValueError", "KeyError", "OSError",
        "SystemExit", "FileNotFoundError", "AssertionError", "OTHER",
    }
    markers = [
        line.removeprefix("PROBE=")
        for line in result.stdout.splitlines()
        if line.startswith("PROBE=") and line.removeprefix("PROBE=") in stages
    ]
    errors = [
        line.removeprefix("PROBE_ERROR=")
        for line in result.stdout.splitlines()
        if line.startswith("PROBE_ERROR=") and line.removeprefix("PROBE_ERROR=") in error_classes
    ]
    if "IMPORT_OK" in markers:
        stage = "IMPORT_OK"
    elif "IMPORT_FAILED" in markers:
        stage = "IMPORT_FAILED"
    elif "PYTHON_STARTED" in markers:
        stage = "PYTHON_STARTED"
    else:
        stage = "PROCESS_NOT_STARTED"

    accepted = {
        "IMPORT_FAILED", "PERSISTENCE_DISABLED", "CONFIG_INVALID",
        "CONFIG_MISMATCH", "READ_CONFIRMED", "DATABASE_READ_FAILED",
    }
    terminal = [m for m in markers if m in accepted]
    outcome = terminal[0] if len(terminal) == 1 else "UNCLASSIFIED_FAILURE"
    if result.returncode == 0 and outcome != "READ_CONFIRMED":
        outcome = "UNCLASSIFIED_FAILURE"
    if result.returncode != 0 and outcome == "READ_CONFIRMED":
        outcome = "UNCLASSIFIED_FAILURE"
    if outcome == "READ_CONFIRMED":
        stage = "ORM_READ_OK"
    elif outcome == "DATABASE_READ_FAILED":
        stage = "ORM_READ_FAILED"
    elif outcome == "CONFIG_MISMATCH":
        stage = "ORM_CONFIG_MISMATCH"
    return {
        "APP_ORM_READ": outcome,
        "APP_STAGE": stage,
        "APP_PACKAGE": (
            "PRESENT" if "BACKEND_PACKAGE_PRESENT" in markers else
            "MISSING" if "BACKEND_PACKAGE_MISSING" in markers else "UNVERIFIED"
        ),
        "APP_ERROR_CLASS": errors[0] if len(errors) == 1 else "NONE",
        "APP_STDERR_CLASS": classify_stderr(result.stderr),
        "APP_EXIT": "ZERO" if result.returncode == 0 else "NONZERO",
    }


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
    result = {
        "STATUS": "DIAGNOSTIC_COMPLETE",
        "CHANGED": False,
        "STATE": "UNCHANGED" if current_sha == former_sha else "DIFFERENT",
        "CURRENT_SHA256": current_sha,
        "BACKUP_FOR_PREVIOUS_STATE": check_backup(former_sha),
        "AUDIT": "READ_ONLY",
    }
    result.update(probe_app(current_sha))
    return result


if __name__ == "__main__":
    try:
        result = audit(json.load(sys.stdin))
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print('{"STATUS":"FAILED_CLOSED","CHANGED":false,"AUDIT":"READ_ONLY"}')
        raise SystemExit(2)
