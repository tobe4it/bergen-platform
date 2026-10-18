"""Token-free, SQLite read-only OIDC identity fingerprint inventory.

Never sends IDs, emails, sub claims or tokens to stdout. A per-run HMAC
challenge is delivered exclusively over stdin and forgotten after the run.
"""
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


class Unsafe(Exception):
    pass


def seal(secret, value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise Unsafe("Invalid identity")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def read_rows(dbpath, secret, provider):
    if not isinstance(provider, str) or not provider or len(provider) > 80:
        raise Unsafe("Missing provider allowlist")
    uri = Path(dbpath).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {x[0] for x in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "user" not in tables:
            raise Unsafe("Missing user table")
        rows = db.execute('SELECT email,role,oauth FROM "user"').fetchall()
        if len(rows) > 1000:
            raise Unsafe("Too many users")
    out = []
    seen = set()
    for email, role, oauth in rows:
        if not oauth:
            continue
        account = json.loads(oauth) if isinstance(oauth, str) else oauth
        if not isinstance(account, dict):
            raise Unsafe("Unexpected OAuth model")
        if provider not in account:
            continue
        data = account[provider]
        if not isinstance(data, dict) or not isinstance(data.get("sub"), str):
            raise Unsafe("Bad provider subject")
        norm_email = email.strip().casefold() if isinstance(email, str) else ""
        if not norm_email or len(norm_email) > 320 or norm_email in seen:
            raise Unsafe("Ambiguous account email")
        if role not in ("admin", "user", "pending"):
            raise Unsafe("Unknown role")
        seen.add(norm_email)
        out.append({
            "email": seal(secret, norm_email),
            "subject": seal(secret, data["sub"]),
            "role": "ADMIN" if role == "admin" else "USER" if role == "user" else "PENDING",
        })
    return sorted(out, key=lambda x: x["email"])


def main():
    try:
        req = json.load(sys.stdin)
        if not isinstance(req, dict) or req.get("version") != "0.10.2":
            raise Unsafe("Unknown application version")
        key = req.get("key")
        if not isinstance(key, str) or len(key) < 48 or len(key) > 120:
            raise Unsafe("Invalid ephemeral HMAC key")
        container = json.loads(subprocess.check_output(
            ["podman", "inspect", "open-webui"], text=True,
            stderr=subprocess.DEVNULL, timeout=15
        ))
        if not isinstance(container, list) or len(container) != 1:
            raise Unsafe("Unexpected container")
        mount = [m.get("Source") for m in container[0].get("Mounts", [])
                 if m.get("Destination") == "/app/backend/data"]
        if mount != ["/srv/ai/open-webui"]:
            raise Unsafe("Wrong storage")
        envs = container[0].get("Config", {}).get("Env", [])
        if not isinstance(envs, list):
            raise Unsafe("Wrong environment")
        env = dict(e.split("=", 1) for e in envs if isinstance(e, str) and "=" in e)
        if any(x in env for x in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
            raise Unsafe("Unsupported external DB")
        path = Path(mount[0]) / "webui.db"
        if not path.is_file():
            raise Unsafe("No database")
        records = read_rows(path, key, req.get("provider"))
        print(json.dumps({"AUDIT": "READ_ONLY", "SYSTEM": "BERGEN_AI",
                          "ACCOUNTS": records, "COUNT": len(records)},
                         sort_keys=True))
    except Exception:
        print('{"AUDIT":"FAILED_CLOSED"}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
