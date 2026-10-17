#!/usr/bin/env python3
"""Root-owned, site-local settings shared by the Synology Paperless agents.

The code contains no fixed NAS path, LDAP home, username or SSH endpoint.
This config holds NO credentials; the private SSH key remains in the user's
SSH directory and is never stored in Git or in the JSON settings.
"""
import json
import os
import pwd
import re
import stat
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().with_name("synology-paperless.json")


def _absolute_path(value, field):
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        raise RuntimeError("INVALID_CONFIG_PATH " + field)
    path = Path(value)
    if str(path) != value or ".." in path.parts or path == Path("/"):
        raise RuntimeError("INVALID_CONFIG_PATH " + field)
    return path


def load():
    info = CONFIG_PATH.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o644):
        raise RuntimeError("UNSAFE_CONFIG " + str(CONFIG_PATH))
    parent = CONFIG_PATH.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or stat.S_IMODE(parent.st_mode) != 0o755):
        raise RuntimeError("UNSAFE_CONFIG_PARENT " + str(CONFIG_PATH.parent))
    if info.st_size > 32768:
        raise RuntimeError("CONFIG_TOO_LARGE")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    required = {
        "schema_version", "state_root", "state_parent", "sync_user",
        "sources", "ssh_identity", "destination", "quiet_seconds",
        "max_size_bytes", "max_files_per_run", "quiet_after_event_seconds",
        "full_scan_seconds", "sender_timeout_seconds",
    }
    if not isinstance(data, dict) or set(data) != required or data["schema_version"] != 1:
        raise RuntimeError("INVALID_CONFIG_SCHEMA")
    root = _absolute_path(data["state_root"], "state_root")
    parent_dir = _absolute_path(data["state_parent"], "state_parent")
    if parent_dir.parent != root:
        raise RuntimeError("STATE_PARENT_NOT_DIRECTLY_BELOW_ROOT")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", data["sync_user"]):
        raise RuntimeError("INVALID_SYNC_USER")
    pwd.getpwnam(data["sync_user"])
    if not isinstance(data["sources"], list) or not 1 <= len(data["sources"]) <= 64:
        raise RuntimeError("INVALID_SOURCES")
    found_paths, found_scopes, sources = set(), set(), []
    for entry in data["sources"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "scope"}:
            raise RuntimeError("INVALID_SOURCE_ENTRY")
        source = _absolute_path(entry["path"], "sources.path")
        scope = entry["scope"]
        if (not isinstance(scope, str) or len(scope) > 120 or
                not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", scope) or
                any(part in ("", ".", "..") for part in scope.split("/"))):
            raise RuntimeError("INVALID_SCOPE")
        if str(source) in found_paths or scope in found_scopes:
            raise RuntimeError("DUPLICATE_SOURCE_OR_SCOPE")
        found_paths.add(str(source))
        found_scopes.add(scope)
        sources.append((source, scope))
    identity = data["ssh_identity"]
    if not isinstance(identity, str) or "\x00" in identity:
        raise RuntimeError("INVALID_IDENTITY")
    if identity.startswith("~/"):
        identity = Path.home() / identity[2:]
    else:
        identity = _absolute_path(identity, "ssh_identity")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*", data["destination"]):
        raise RuntimeError("INVALID_DESTINATION")
    for key, minimum, maximum in (
        ("quiet_seconds", 30, 3600),
        ("max_size_bytes", 1024, 1024 * 1024 * 1024),
        ("max_files_per_run", 1, 10000),
        ("quiet_after_event_seconds", 30, 7200),
        ("full_scan_seconds", 60, 86400),
        ("sender_timeout_seconds", 60, 86400),
    ):
        value = data[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise RuntimeError("INVALID_CONFIG_NUMBER " + key)
    if data["quiet_after_event_seconds"] < data["quiet_seconds"]:
        raise RuntimeError("EVENT_DELAY_SHORTER_THAN_QUIET_TIME")
    return {
        "root": root,
        "parent": parent_dir,
        "state": parent_dir / data["sync_user"],
        "gate": parent_dir / "synology-sync.enabled",
        "sync_user": data["sync_user"],
        "sources": tuple(sources),
        "identity": Path(identity),
        "destination": data["destination"],
        "quiet": data["quiet_seconds"],
        "max_size": data["max_size_bytes"],
        "max_files": data["max_files_per_run"],
        "event_delay": data["quiet_after_event_seconds"],
        "full_scan": data["full_scan_seconds"],
        "sender_timeout": data["sender_timeout_seconds"],
    }


SETTINGS = load()
