#!/usr/bin/env python3
"""Sanitized, exact-mx1 read-only dependencies audit before retiring old Cloud.

Never prints nginx content, TLS file names, secret values, database rows or users.
No delete, edits, package changes, certbot commands, service changes or network calls.
"""
import json
import os
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

ROOT = "/usr/share/nginx/de.tbergen.cloud/html"
CLOUD = "cloud.tbergen.de"
CONFIG_MARKER = re.compile(r"(?m)^# configuration file ([^\n:]+):\s*$")
CLOUD_REFERENCE = re.compile(r"(?<![A-Za-z0-9.-])cloud\.tbergen\.de(?![A-Za-z0-9.-])", re.I)
NGINX_CERT = re.compile(r"(?m)^\s*ssl_certificate\s+([^;#\n]+);")
ALLOWED_CONFIG = re.compile(
    r"^/etc/nginx/(?:nginx\.conf|conf\.d/[A-Za-z0-9._-]+\.conf|"
    r"sites-(?:available|enabled)/[A-Za-z0-9._-]+)$"
)
MAX_OUTPUT = 2_500_000

class Blocked(Exception):
    pass

def require(value, code):
    if not value:
        raise Blocked(code)

def command(argv, timeout=35):
    require(argv and argv[0] in
            ("hostname", "nginx", "findmnt", "systemctl",
             "mariadb", "postconf", "doveconf"), "COMMAND_NOT_ALLOWED")
    try:
        result = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(result.stdout) > MAX_OUTPUT:
        raise Blocked("READ_RESULT_TOO_LARGE")
    return result if result.returncode == 0 else None

def nginx_inventory():
    result = command(["nginx", "-T"])
    if result is None:
        return {"state": "NGINX_CONFIG_UNAVAILABLE", "exclusive": False}
    sections = {}
    markers = list(CONFIG_MARKER.finditer(result.stdout))
    require(0 < len(markers) <= 256, "NGINX_CONFIG_MARKERS_UNEXPECTED")
    for i, match in enumerate(markers):
        name = match.group(1).strip()
        require(len(name) <= 256, "NGINX_CONFIG_PATH_UNBOUNDED")
        body = result.stdout[match.end():markers[i+1].start()
                             if i+1 < len(markers) else len(result.stdout)]
        require(len(body) <= MAX_OUTPUT, "NGINX_SECTION_UNBOUNDED")
        sections.setdefault(name, []).append(body)
    cloud_files = sorted(n for n, chunks in sections.items()
                         if any(CLOUD_REFERENCE.search(s) or ROOT in s
                                for s in chunks))
    require(len(cloud_files) <= 30, "NGINX_LEGACY_REFERENCE_SCOPE_UNBOUNDED")
    allowlisted = [n for n in cloud_files if ALLOWED_CONFIG.fullmatch(n)]
    unknown_count = len(cloud_files) - len(allowlisted)
    clouds = {n for n in cloud_files}
    cert_refs = set()
    all_certs = {}
    for n, chunks in sections.items():
        found = set()
        for chunk in chunks:
            found.update(v.strip().strip("\"'") for v in NGINX_CERT.findall(chunk))
        all_certs[n] = found
        if n in clouds:
            cert_refs.update(found)
    other_users = {n for n in all_certs if n not in clouds and
                   cert_refs.intersection(all_certs[n])}
    root_other = [n for n, chunks in sections.items() if n not in clouds and
                  any(ROOT in s for s in chunks)]
    return {
        "state": "EFFECTIVE_NGINX_SYNTAX_OK",
        "scanned_config_count": len(sections),
        "legacy_reference_file_count": len(cloud_files),
        "legacy_reference_allowlisted_files": allowlisted,
        "legacy_reference_nonallowlisted_count": unknown_count,
        "cloud_server_name_declarations": sum(
            len(re.findall(r"(?m)^\s*server_name\s+[^;]*\bcloud\.tbergen\.de\b", s, re.I))
            for chunks in sections.values() for s in chunks
        ),
        "office_reference_file_count": sum(
            any("office.tbergen.de" in s for s in chunks)
            for chunks in sections.values()
        ),
        "literal_certificate_reused_in_other_config_count": len(other_users),
        "literal_certificate_reuse_found": bool(other_users),
        "legacy_root_reference_in_other_file_count": len(root_other),
        "certificate_consumers_fully_proven": False,
        "exclusive": False,
    }

def cert_source_classification():
    """Only compare internal paths; never emit any TLS path or material."""
    commands = [
        ["postconf", "-h", "smtpd_tls_cert_file"],
        ["postconf", "-h", "smtpd_tls_eccert_file"],
        ["postconf", "-h", "smtpd_tls_chain_files"],
        ["doveconf", "-h", "ssl_cert"],
    ]
    observed = 0
    unresolved = 0
    for cmd in commands:
        p = command(cmd, timeout=15)
        if p is None:
            unresolved += 1
        elif p.stdout.strip():
            observed += 1
    return {
        "mail_tls_consumer_settings_seen": observed,
        "mail_tls_consumer_settings_unavailable": unresolved,
        "shared_certificate_deletion_authorized": False,
    }

def old_tree():
    root = Path(ROOT)
    parts = (Path("/usr"), Path("/usr/share"), Path("/usr/share/nginx"),
             Path("/usr/share/nginx/de.tbergen.cloud"), root)
    unsafe = False
    for part in parts:
        try:
            metadata = part.lstat()
        except OSError:
            unsafe = True
            break
        if not stat.S_ISDIR(metadata.st_mode) or part.is_symlink():
            unsafe = True
            break
    mounts = command(["findmnt", "-rn", "-o", "TARGET"])
    nested = None if mounts is None else sum(
        line.strip().startswith(ROOT + "/") for line in mounts.stdout.splitlines()
    )
    return {
        "parent_components_directory_without_symlinks": not unsafe,
        "nested_mount_count": nested,
        "tree_deletion_authorized": False,
    }

def database_scope():
    sql = ("SELECT COUNT(*) FROM information_schema.SCHEMATA "
           "WHERE SCHEMA_NAME='nextcloud'")
    p = command(["mariadb", "--protocol=socket", "--batch",
                 "--skip-column-names", "-e", sql], timeout=20)
    state = ("PRESENT" if p and p.stdout.strip() == "1" else
             "ABSENT" if p and p.stdout.strip() == "0" else "UNKNOWN")
    return {
        "legacy_nextcloud_schema": state,
        "other_schema_ownership_verified": False,
        "database_drop_authorized": False,
    }

def scheduling_scope():
    p = command(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    return {
        "systemd_timers_readable": p is not None,
        "nextcloud_named_timer_matches": (
            sum(bool(re.search(r"nextcloud|cloud\.tbergen", x, re.I))
                for x in p.stdout.splitlines())
            if p else None
        ),
        "timer_removal_authorized": False,
    }

def run(expected):
    require(re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", expected), "BAD_HOST_ID")
    p = command(["hostname", "-f"])
    require(p is not None and p.stdout.strip() == expected,
            "NOT_VERIFIED_MX1")
    require(expected != "mx.thebergens.net", "PRODUCTION_MX2_IS_FORBIDDEN")
    require(os.geteuid() == 0, "ROOT_AUDIT_REQUIRED")
    require(socket.gethostname() != "", "HOSTNAME_UNAVAILABLE")
    return {
        "result": "MX1_NEXTCLOUD_DEPENDENCIES_READ_ONLY_RECORDED",
        "host_identity": "VERIFIED_MX1",
        "nginx": nginx_inventory(),
        "mail_certificate_settings": cert_source_classification(),
        "old_tree": old_tree(),
        "database": database_scope(),
        "scheduling": scheduling_scope(),
        "files_written": 0,
        "services_changed": 0,
        "mail_changed": False,
        "mx2_changed": False,
        "deletion_authorized": False,
        "dependency_exclusivity_proven": False,
    }

if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2, "ONE_EXPECTED_HOST_REQUIRED")
        print(json.dumps(run(sys.argv[1]), sort_keys=True))
    except Blocked as error:
        print(json.dumps({
            "result": "MX1_NEXTCLOUD_DEPENDENCIES_READ_ONLY_BLOCKED",
            "reason": str(error),
            "deletion_authorized": False
        }, sort_keys=True))
        sys.exit(1)
