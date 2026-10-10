#!/usr/bin/env python3
"""Certbot DNS-01 auth/cleanup using dedicated selfHOST API TXT slots.

Run as root on the certificate source, using only private local configuration.
The hook emits ONLY its numeric record ID to stdout for Certbot cleanup.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

API_URL = "https://my.selfhost.de/cgi-bin/dns-api.pl"
DEFAULT_CONFIG = "/etc/letsencrypt/selfhost-acme.json"
DEFAULT_STATE_DIR = "/var/lib/selfhost-acme"
DNS01 = re.compile(r"^[A-Za-z0-9_-]{43}$")
DOMAIN = re.compile(r"^[a-z0-9.-]+$")


class HookError(Exception):
    pass


def _private_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise HookError("Missing or unsafe local configuration file")
    stats = path.stat()
    if stats.st_uid != 0 or stats.st_mode & 0o077:
        raise HookError("Local configuration must be owned by root and mode 0600")
    return path


def load_config(path=DEFAULT_CONFIG):
    with _private_file(path).open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise HookError("Invalid local configuration")
    key = cfg.get("api_key")
    zone = cfg.get("zone")
    slots = cfg.get("record_ids")
    servers = cfg.get("nameservers")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", key):
        raise HookError("Missing or invalid API key format in local config")
    if not isinstance(zone, str) or not DOMAIN.fullmatch(zone) or ".." in zone:
        raise HookError("Invalid zone in local config")
    if not isinstance(slots, list) or len(slots) != 2 or len(set(slots)) != 2 or any(
        type(s) is not int or s <= 0 for s in slots
    ):
        raise HookError("Exactly two distinct numeric record IDs are required")
    if not isinstance(servers, list) or len(servers) < 2 or any(
        not isinstance(s, str) or not DOMAIN.fullmatch(s) for s in servers
    ):
        raise HookError("At least two authoritative nameservers are required")
    return cfg


def certbot_context(cfg, env):
    identifier = env.get("CERTBOT_IDENTIFIER") or env.get("CERTBOT_DOMAIN", "")
    validation = env.get("CERTBOT_VALIDATION", "")
    if identifier not in (cfg["zone"], "*." + cfg["zone"]):
        raise HookError("Certbot requested an unapproved domain")
    if not DNS01.fullmatch(validation):
        raise HookError("Certbot DNS-01 validation value malformed")
    return identifier, validation


@contextmanager
def exclusive_state(path=DEFAULT_STATE_DIR):
    state_dir = Path(path)
    if state_dir.is_symlink():
        raise HookError("Unsafe state directory symlink")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stats = state_dir.stat()
    if stats.st_uid != os.geteuid() or stats.st_mode & 0o077:
        raise HookError("State directory must be owned by the running user and mode 0700")
    lock_path = state_dir / "lock"
    if lock_path.is_symlink():
        raise HookError("Unsafe lock-file symlink")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.geteuid() or os.fstat(fd).st_mode & 0o077:
            raise HookError("Unsafe state lock permissions")
        fcntl.flock(fd, fcntl.LOCK_EX)
        state_path = state_dir / "active.json"
        if state_path.is_symlink():
            raise HookError("Unsafe state symlink")
        if state_path.exists():
            if state_path.stat().st_uid != os.geteuid() or state_path.stat().st_mode & 0o077:
                raise HookError("Unsafe state-file permissions")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise HookError("Corrupt state file")
        else:
            state = {}
        yield state, state_path
    finally:
        os.close(fd)


def save_state(path, state):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         prefix=".active.", dir=path.parent,
                                         delete=False) as fh:
            tmp = Path(fh.name)
            os.fchmod(fh.fileno(), 0o600)
            json.dump(state, fh, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def api_request(cfg, action, record_id, validation):
    payload = json.dumps({
        "api_key": cfg["api_key"],
        "action": action,
        "record_id": record_id,
        "content": validation,
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=15) as response:
            if response.status != 202:
                raise HookError("selfHOST did not acknowledge the change (expected HTTP 202)")
            response.read(4096)
    except urllib.error.HTTPError as exc:
        raise HookError(f"selfHOST API rejected {action} with HTTP {exc.code}; review slot state") from exc
    except urllib.error.URLError as exc:
        raise HookError("selfHOST API request failed; remote slot state uncertain") from exc


def authoritative_txt(server, name):
    result = subprocess.run(
        ["dig", "+short", "+norecurse", "+time=3", "+tries=1",
         "TXT", name, "@" + server],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=False, timeout=8, text=True,
    )
    if result.returncode:
        return set()
    return {line.strip().strip('"') for line in result.stdout.splitlines()}


def wait_for_dns(cfg, value, seconds=300, pause=10):
    fqdn = "_acme-challenge." + cfg["zone"]
    until = time.monotonic() + seconds
    while True:
        if all(value in authoritative_txt(server, fqdn) for server in cfg["nameservers"]):
            return
        if time.monotonic() >= until:
            raise HookError("DNS propagation not confirmed on all authoritative nameservers")
        time.sleep(pause)


def present(cfg, env, state_dir=DEFAULT_STATE_DIR):
    identifier, validation = certbot_context(cfg, env)
    with exclusive_state(state_dir) as (state, path):
        if any(entry.get("validation") == validation for entry in state.values()):
            raise HookError("Challenge already reserved; inspect local state")
        available = [s for s in cfg["record_ids"] if str(s) not in state]
        if not available:
            raise HookError("Both TXT slots are occupied; do not overwrite another challenge")
        record_id = available[0]
        state[str(record_id)] = {"identifier": identifier,
                                 "validation": validation, "status": "reserved"}
        save_state(path, state)
        api_request(cfg, "present", record_id, validation)
        state[str(record_id)]["status"] = "presented"
        save_state(path, state)
        wait_for_dns(cfg, validation)
        print(record_id)


def cleanup(cfg, env, state_dir=DEFAULT_STATE_DIR):
    identifier, validation = certbot_context(cfg, env)
    try:
        record_id = int(env.get("CERTBOT_AUTH_OUTPUT", "").strip())
    except ValueError as exc:
        raise HookError("Certbot cleanup lacks valid auth record ID") from exc
    if record_id not in cfg["record_ids"]:
        raise HookError("Certbot cleanup references an unknown record ID")
    with exclusive_state(state_dir) as (state, path):
        entry = state.get(str(record_id))
        if not entry or entry["identifier"] != identifier or entry["validation"] != validation:
            raise HookError("Cleanup does not match the recorded challenge; refusing mutation")
        if entry["status"] not in ("presented", "cleaning"):
            raise HookError("Challenge was not confirmed presented; manual review required")
        if entry["status"] == "presented":
            state[str(record_id)]["status"] = "cleaning"
            save_state(path, state)
            api_request(cfg, "cleanup", record_id, validation)
        wait_for_dns(cfg, "selfhost-api-idle-" + str(record_id))
        del state[str(record_id)]
        save_state(path, state)


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    if len(argv) != 1 or argv[0] not in ("auth", "cleanup"):
        raise HookError("Usage: selfhost_acme_hook.py auth|cleanup")
    if os.geteuid() != 0:
        raise HookError("Certbot selfHOST hook must be executed as root")
    os.umask(0o077)
    cfg = load_config(environ.get("SELFHOST_ACME_CONFIG", DEFAULT_CONFIG))
    if argv[0] == "auth":
        present(cfg, environ)
    else:
        cleanup(cfg, environ)


if __name__ == "__main__":
    try:
        main()
    except (HookError, OSError, ValueError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        print("selfHOST DNS-01 hook failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
