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


# Closed set of non-identifying failure classifications. Never display raw
# exception text, DB values, user fields or runtime metadata.
SAFE_FAILURE_CODES = frozenset({
    "INVALID_IDENTITY", "INVALID_PROVIDER_SELECTOR", "NO_USER_TABLE",
    "EXCESSIVE_USER_COUNT", "OAUTH_JSON_INVALID", "OAUTH_SHAPE_INVALID",
    "OAUTH_SUBJECT_INVALID", "OAUTH_EMAIL_AMBIGUOUS", "ROLE_UNREVIEWED",
    "APP_VERSION_UNREVIEWED", "CHALLENGE_INVALID", "CONTAINER_UNEXPECTED",
    "STORAGE_UNEXPECTED", "CONTAINER_ENV_UNEXPECTED", "DATABASE_EXTERNAL",
    "DATABASE_MISSING",
})


def report_failure(code):
    if code not in SAFE_FAILURE_CODES and code not in {
        "DB_READ_ERROR", "RUNTIME_INSPECTION_ERROR", "INPUT_JSON_INVALID",
        "UNEXPECTED_INTERNAL_ERROR",
    }:
        code = "UNEXPECTED_INTERNAL_ERROR"
    print(json.dumps({"AUDIT": "FAILED_CLOSED", "CODE": code}, sort_keys=True))



def seal(secret, value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise Unsafe("INVALID_IDENTITY")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def read_rows(dbpath, secret, provider):
    if not isinstance(provider, str) or not provider or len(provider) > 80:
        raise Unsafe("INVALID_PROVIDER_SELECTOR")
    uri = Path(dbpath).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        tables = {x[0] for x in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "user" not in tables:
            raise Unsafe("NO_USER_TABLE")
        rows = db.execute('SELECT email,role,oauth FROM "user"').fetchall()
        if len(rows) > 1000:
            raise Unsafe("EXCESSIVE_USER_COUNT")
    out = []
    seen = set()
    for email, role, oauth in rows:
        if not oauth:
            continue
        try:
            account = json.loads(oauth) if isinstance(oauth, str) else oauth
        except (ValueError, TypeError):
            raise Unsafe("OAUTH_JSON_INVALID") from None
        if not isinstance(account, dict):
            raise Unsafe("OAUTH_SHAPE_INVALID")
        if provider not in account:
            continue
        data = account[provider]
        if not isinstance(data, dict) or not isinstance(data.get("sub"), str):
            raise Unsafe("OAUTH_SUBJECT_INVALID")
        norm_email = email.strip().casefold() if isinstance(email, str) else ""
        if not norm_email or len(norm_email) > 320 or norm_email in seen:
            raise Unsafe("OAUTH_EMAIL_AMBIGUOUS")
        if role not in ("admin", "user", "pending"):
            raise Unsafe("ROLE_UNREVIEWED")
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
            raise Unsafe("APP_VERSION_UNREVIEWED")
        key = req.get("key")
        if not isinstance(key, str) or len(key) < 48 or len(key) > 120:
            raise Unsafe("CHALLENGE_INVALID")
        container = json.loads(subprocess.check_output(
            ["podman", "inspect", "open-webui"], text=True,
            stderr=subprocess.DEVNULL, timeout=15
        ))
        if not isinstance(container, list) or len(container) != 1:
            raise Unsafe("CONTAINER_UNEXPECTED")
        mount = [m.get("Source") for m in container[0].get("Mounts", [])
                 if m.get("Destination") == "/app/backend/data"]
        if mount != ["/srv/ai/open-webui"]:
            raise Unsafe("STORAGE_UNEXPECTED")
        envs = container[0].get("Config", {}).get("Env", [])
        if not isinstance(envs, list):
            raise Unsafe("CONTAINER_ENV_UNEXPECTED")
        env = dict(e.split("=", 1) for e in envs if isinstance(e, str) and "=" in e)
        if any(x in env for x in ("DATABASE_URL", "DATABASE_TYPE", "DATABASE_USER")):
            raise Unsafe("DATABASE_EXTERNAL")
        path = Path(mount[0]) / "webui.db"
        if not path.is_file():
            raise Unsafe("DATABASE_MISSING")
        records = read_rows(path, key, req.get("provider"))
        print(json.dumps({"AUDIT": "READ_ONLY", "SYSTEM": "BERGEN_AI",
                          "ACCOUNTS": records, "COUNT": len(records)},
                         sort_keys=True))
    except Unsafe as err:
        report_failure(str(err))
        raise SystemExit(2)
    except sqlite3.Error:
        report_failure("DB_READ_ERROR")
        raise SystemExit(2)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        report_failure("RUNTIME_INSPECTION_ERROR")
        raise SystemExit(2)
    except json.JSONDecodeError:
        report_failure("INPUT_JSON_INVALID")
        raise SystemExit(2)
    except Exception:
        report_failure("UNEXPECTED_INTERNAL_ERROR")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
