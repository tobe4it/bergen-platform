"""Bounded live-Nginx repair for Paperless-ngx native chat streaming.

Reads or atomically patches exactly one existing Paperless vhost on CT125.
Default audit, SHA-pinned explicit apply. Never changes any other vhost,
credentials, ACL, certificate, firewall rule, SSH unit, or backend service.
No shell invocation or raw Nginx error logs emitted.
"""
import hashlib
import json
import os
import pathlib
import re
import socket
import stat
import subprocess
import sys
import tempfile

FRAME = "BERGEN_PAPERLESS_CHAT_NGINX_V1:"
VHOST = pathlib.Path(
    "/etc/nginx/sites-enabled/50-internal-paperless.thebergens.net.conf"
)
EXPECTED_DEST = pathlib.Path(
    "/etc/nginx/sites-available/50-internal-paperless.thebergens.net.conf"
)
HOSTNAME = "paperless.thebergens.net"
UPSTREAM = "http://127.0.0.1:18000"
CHAT_PATH = "/api/documents/chat/"
TIMEOUT = "300s"
MODEL = "nginx-vhost-native-chat-v1"

LOCATION = """    location = /api/documents/chat/ {
        proxy_pass http://127.0.0.1:18000;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_buffering off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $reverse_proxy_connection_upgrade;
    }

"""
FRAME_MAX = 1600


class Refusal(Exception):
    pass


def check(yes, code):
    if not yes:
        raise Refusal(code)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def emit(status, **fields):
    data = dict(STATUS=status, CHANGE="NO", **fields)
    rendered = FRAME + json.dumps(data, sort_keys=True, separators=(",", ":"))
    check(len(rendered) <= FRAME_MAX, "OUTPUT_TOO_LONG")
    print(rendered, flush=True)


def command_ok(args):
    try:
        out = subprocess.run(args, capture_output=True, timeout=12, check=False)
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def read_config():
    check(socket.gethostname().split(".")[0] == "bergen-proxy",
          "WRONG_PROXY_GUEST")
    check(VHOST.is_symlink() and VHOST.resolve(strict=True) == EXPECTED_DEST,
          "VHOST_PATH_UNREVIEWED")
    check(EXPECTED_DEST.is_file() and not EXPECTED_DEST.is_symlink(),
          "VHOST_TARGET_UNREVIEWED")
    st = EXPECTED_DEST.stat()
    check(st.st_uid == 0 and st.st_gid == 0 and
          stat.S_IMODE(st.st_mode) == 0o644, "VHOST_OWNER_MODE_UNREVIEWED")
    check(st.st_size < 32768, "VHOST_TOO_LARGE")
    data = EXPECTED_DEST.read_bytes()
    check(len(data) == st.st_size, "VHOST_SIZE_DRIFT")
    try:
        content = data.decode("utf-8")
    except UnicodeError:
        raise Refusal("VHOST_ENCODING_UNREVIEWED")
    return data, content, st


def candidate(content):
    check(content.startswith("# Managed by Ansible: paperless.thebergens.net\n"),
          "VHOST_TEMPLATE_UNREVIEWED")
    check(content.count("server {") == 1 and
          content.count("server_name paperless.thebergens.net;") == 1,
          "VHOST_SCOPE_UNREVIEWED")
    check(content.count("listen 443 ssl;") == 1 and
          content.count("    proxy_read_timeout 120s;") == 1,
          "VHOST_BASELINE_UNREVIEWED")
    check("ssl_certificate " in content and
          "ssl_certificate_key " in content and
          "    deny all;" in content and
          bool(re.search(r"^\s+allow\s+\S+;", content, re.M)),
          "VHOST_TLS_OR_ALLOWLIST_UNREVIEWED")
    check("0.0.0.0/0" not in content and "::/0" not in content,
          "VHOST_ALLOWLIST_UNSAFE")
    check("    location / {\n" in content and
          content.count("    location / {\n") == 1,
          "ROOT_LOCATION_UNREVIEWED")
    check("        proxy_pass http://127.0.0.1:18000;" in content,
          "PAPERLESS_UPSTREAM_UNREVIEWED")
    forwarded = (
        "Host $host", "X-Real-IP $remote_addr",
        "X-Forwarded-For $remote_addr", "X-Forwarded-Host $host",
        "X-Forwarded-Proto $scheme", "Upgrade $http_upgrade",
        "Connection $reverse_proxy_connection_upgrade",
    )
    for header in forwarded:
        check("        proxy_set_header " + header + ";" in content,
              "ROOT_HEADERS_UNREVIEWED")
    chat_present = LOCATION in content
    check(
        len(re.findall(r"^\s+location\s+", content, re.M)) == (
            2 if chat_present else 1
        ),
        "EXTRA_LOCATION_UNREVIEWED",
    )
    check(content.count("location = " + CHAT_PATH) ==
          (1 if chat_present else 0), "CONFLICTING_CHAT_LOCATION")
    if chat_present:
        check(content.replace(LOCATION, "", 1).count("location = " + CHAT_PATH)
              == 0, "DUPLICATE_CHAT_LOCATION")
        return content, True
    return content.replace("    location / {\n", LOCATION + "    location / {\n", 1), False


def write_atomic(data, old_stat):
    """Single file replacement; preserve mode/ownership and sync prior to rename."""
    temp = None
    try:
        fd, temp = tempfile.mkstemp(
            prefix=".bp-chat-nginx-", dir=str(EXPECTED_DEST.parent)
        )
        with os.fdopen(fd, "wb") as file:
            os.fchown(file.fileno(), old_stat.st_uid, old_stat.st_gid)
            os.fchmod(file.fileno(), stat.S_IMODE(old_stat.st_mode))
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, EXPECTED_DEST)
        temp = None
    finally:
        if temp is not None and os.path.exists(temp):
            os.unlink(temp)


def main():
    status = "BLOCKED"
    mode = "NOT_PROVEN"
    try:
        check(len(sys.argv) == 4, "ARGUMENTS_UNREVIEWED")
        mode, expected, approval = sys.argv[1:]
        check(mode in ("audit", "apply") and approval in ("0", "1") and
              (mode == "apply") == (approval == "1"),
              "MODE_APPROVAL_UNREVIEWED")
        check(mode != "apply" or re.fullmatch(r"[a-f0-9]{64}", expected),
              "EXPECTED_SHA_UNREVIEWED")
        check(mode != "audit" or expected == "NONE",
              "AUDIT_EXPECTED_SHA_UNREVIEWED")

        old_bytes, old_text, old_stat = read_config()
        wanted_text, already = candidate(old_text)
        check(command_ok(["nginx", "-t"]), "NGINX_BASELINE_BAD")
        check(command_ok(["systemctl", "is-active", "--quiet", "nginx"]),
              "NGINX_NOT_ACTIVE")
        fingerprint = sha(old_bytes)
        if mode == "audit":
            emit("ALREADY_APPLIED" if already else "READY_FOR_APPLY",
                 MODE="AUDIT", CURRENT_SHA256=fingerprint,
                 DEDICATED_CHAT_LOCATION="YES" if already else "NO",
                 CHAT_BUFFERING_OFF="YES" if already else "NO",
                 CHAT_READ_TIMEOUT=TIMEOUT if already else "120s",
                 SERVER_ALLOWLIST_UNCHANGED="YES",
                 CHANGED=False)
            return

        check(fingerprint == expected, "BASELINE_SHA_DRIFT")
        if already:
            emit("ALREADY_APPLIED", MODE="APPLY",
                 CURRENT_SHA256=fingerprint,
                 DEDICATED_CHAT_LOCATION="YES",
                 CHAT_BUFFERING_OFF="YES",
                 CHAT_READ_TIMEOUT=TIMEOUT,
                 SERVER_ALLOWLIST_UNCHANGED="YES", CHANGED=False)
            return
        new_bytes = wanted_text.encode("utf-8")
        check(wanted_text.replace(LOCATION, "", 1) == old_text,
              "NON_CHAT_CONTENT_CHANGED")
        # A strict fail-closed patch: write and validate Nginx before reload.
        write_atomic(new_bytes, old_stat)
        applied = False
        try:
            check(command_ok(["nginx", "-t"]), "NGINX_NEW_SYNTAX_BAD")
            check(command_ok(["systemctl", "reload", "nginx"]),
                  "NGINX_RELOAD_FAILED")
            actual, text, _st = read_config()
            check(actual == new_bytes and candidate(text)[1],
                  "VHOST_POST_VERIFY_FAILED")
            check(command_ok(["nginx", "-t"]), "NGINX_POST_SYNTAX_BAD")
            applied = True
        finally:
            if not applied:
                # Roll back only the named Paperless vhost; no other service.
                write_atomic(old_bytes, old_stat)
                restored, _content, _st = read_config()
                if restored != old_bytes or not command_ok(["nginx", "-t"]):
                    status = "ROLLBACK_UNVERIFIED"
                elif not command_ok(["systemctl", "reload", "nginx"]):
                    status = "ROLLBACK_RELOAD_FAILED"
                else:
                    status = "ROLLED_BACK"
        check(applied, status)
        emit("APPLIED", MODE="APPLY", CURRENT_SHA256=sha(new_bytes),
             SERVER_ALLOWLIST_UNCHANGED="YES",
             DEDICATED_CHAT_LOCATION="YES",
             CHAT_BUFFERING_OFF="YES", CHAT_READ_TIMEOUT=TIMEOUT,
             CHANGED=True)
    except Refusal as e:
        emit("BLOCKED", MODE=mode, REASON=str(e), CHANGED=False)
    except Exception:
        emit("BLOCKED", MODE=mode, REASON="UNCLASSIFIED", CHANGED=False)


main()
