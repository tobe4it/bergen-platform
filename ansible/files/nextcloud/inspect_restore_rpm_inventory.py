#!/usr/bin/env python3
"""Sanitized read-only RPM and repository inventory for a recovery rehearsal.

Only public-style package metadata, module streams, and repository IDs are
emitted. Never copy repository contents, URLs, credentials or config.php.
"""
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ALLOWED_ID = re.compile(r"^[A-Za-z0-9_.+:-]{1,96}$")
ALLOWED_FIELD = re.compile(r"^[A-Za-z0-9_.+~:-]{1,160}$")
PREFIXES = (
    "php", "mariadb", "MariaDB", "nginx", "httpd",
    "redis", "remi", "epel", "libzip", "libicu",
    "oniguruma", "ImageMagick", "imagemagick",
    "libpng", "libjpeg", "libwebp", "mysql", "mod_php",
    "tar", "rsync", "dnf-", "rocky-", "curl", "ca-certificates",
)


class InventoryError(Exception):
    pass


def require(condition, marker):
    if not condition:
        raise InventoryError(marker)


def run_readonly(command, timeout=20):
    try:
        return subprocess.run(
            command, capture_output=True, check=False,
            text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InventoryError("READONLY_COMMAND_UNAVAILABLE") from exc


def os_release():
    values = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("ID", "VERSION_ID"):
            values[key] = value.strip().strip('"').strip("'")
    return values


def package_metadata():
    outcome = run_readonly([
        "rpm", "-qa", "--qf",
        "%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}|%{VENDOR}\n",
    ], timeout=30)
    require(outcome.returncode == 0, "RPM_QUERY_UNAVAILABLE")
    require(len(outcome.stdout) < 2 * 1024 * 1024, "RPM_OUTPUT_TOO_LARGE")
    packages = []
    for line in outcome.stdout.splitlines():
        fields = line.split("|")
        require(len(fields) == 5, "RPM_RECORD_UNEXPECTED")
        name, version, release, arch, vendor = fields
        if not name.startswith(PREFIXES):
            continue
        require(all(ALLOWED_FIELD.fullmatch(x) for x in (name, version, release, arch)),
                "RPM_FIELD_UNEXPECTED")
        vendor = vendor[:100]
        # Vendor names are metadata, not paths. Prevent escape/control chars.
        vendor = "".join(c for c in vendor if c.isalnum() or c in " -._/()")
        packages.append({
            "name": name, "version": version, "release": release,
            "arch": arch, "vendor": vendor,
        })
    packages.sort(key=lambda p: (p["name"], p["arch"]))
    require(len(packages) <= 160, "PACKAGE_INVENTORY_TOO_LARGE")
    return packages


def repo_ids():
    results = set()
    root = Path("/etc/yum.repos.d")
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.repo"))
    require(len(files) <= 60, "TOO_MANY_REPO_CONFIGS")
    for entry in files:
        require(not entry.is_symlink(), "REPO_CONFIG_SYMLINK")
        ini = configparser.RawConfigParser(interpolation=None, strict=False)
        try:
            with entry.open(encoding="utf-8") as handle:
                ini.read_file(handle)
        except (OSError, UnicodeError, configparser.Error) as exc:
            raise InventoryError("REPO_CONFIG_UNPARSABLE") from exc
        for section in ini.sections():
            require(ALLOWED_ID.fullmatch(section), "REPO_IDENTIFIER_UNEXPECTED")
            try:
                enabled = ini.getboolean(section, "enabled", fallback=True)
            except ValueError as exc:
                raise InventoryError("REPO_ENABLED_INVALID") from exc
            if enabled:
                results.add(section)
    require(len(results) <= 60, "TOO_MANY_ENABLED_REPOS")
    return sorted(results)


def module_streams():
    result = []
    module_root = Path("/etc/dnf/modules.d")
    if not module_root.is_dir():
        return []
    modules = sorted(module_root.glob("*.module"))
    require(len(modules) <= 60, "TOO_MANY_MODULE_CONFIGS")
    for f in modules:
        require(not f.is_symlink(), "MODULE_CONFIG_SYMLINK")
        ini = configparser.RawConfigParser(interpolation=None, strict=False)
        try:
            with f.open(encoding="utf-8") as source:
                ini.read_file(source)
        except (OSError, UnicodeError, configparser.Error) as exc:
            raise InventoryError("MODULE_CONFIG_UNPARSABLE") from exc
        for section in ini.sections():
            require(ALLOWED_ID.fullmatch(section), "MODULE_IDENTIFIER_UNEXPECTED")
            state = ini.get(section, "state", fallback="").strip()
            if state != "enabled":
                continue
            stream = ini.get(section, "stream", fallback="").strip()
            require(ALLOWED_ID.fullmatch(stream), "MODULE_STREAM_UNEXPECTED")
            result.append({"module": section, "stream": stream})
    return result


def cached_rpms():
    root = Path("/var/cache/dnf")
    if not root.is_dir():
        return {"count": 0, "total_bytes": 0}
    count, size = 0, 0
    for candidate in root.rglob("*.rpm"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        count += 1
        size += candidate.stat().st_size
        require(count <= 10000, "CACHED_RPM_LIMIT")
    return {"count": count, "total_bytes": size}


def php_modules():
    if not shutil.which("php"):
        return {"available": False, "modules": []}
    result = run_readonly(["php", "-m"])
    if result.returncode:
        return {"available": False, "modules": []}
    modules = sorted({
        x.strip() for x in result.stdout.splitlines()
        if ALLOWED_ID.fullmatch(x.strip()) and x.strip() != "Modules"
    })
    require(len(modules) <= 150, "PHP_MODULE_LIMIT")
    return {"available": True, "modules": modules}


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ("source", "guest"),
            "INVALID_INVENTORY_MODE")
    role = sys.argv[1]
    identity = os_release()
    require(identity.get("ID") in ("rocky", "rhel", "almalinux"),
            "UNEXPECTED_DISTRIBUTION")
    require(identity.get("VERSION_ID", "").startswith("9."),
            "UNEXPECTED_MAJOR_OS")
    if role == "guest":
        import socket
        require(socket.gethostname().split(".")[0] == "nextcloud-restore-701",
                "UNEXPECTED_GUEST_HOSTNAME")
        net = Path("/sys/class/net")
        require((net / "lo").is_symlink(), "MISSING_LOOPBACK")
        require(not any(p.is_symlink() for p in net.iterdir() if p.name != "lo"),
                "EXTERNAL_NETWORK_DEVICE_PRESENT")
    state = {
        "role": role,
        "os_id": identity["ID"],
        "os_version": identity["VERSION_ID"],
        "packages": package_metadata(),
        "enabled_repo_ids": repo_ids(),
        "enabled_module_streams": module_streams(),
        "cached_rpms": cached_rpms() if role == "source" else {"count": 0, "total_bytes": 0},
        "php_extensions": php_modules() if role == "source" else {"available": False, "modules": []},
        "dnf_present": shutil.which("dnf") is not None,
        "network_changes": False,
        "package_installation": False,
        "configuration_contents_revealed": False,
    }
    print(json.dumps(state, sort_keys=True))
    print("NEXTCLOUD_RESTORE_PACKAGE_INVENTORY=COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except InventoryError as exc:
        print("NEXTCLOUD_RESTORE_PACKAGE_INVENTORY_FAILED=" + str(exc))
        sys.exit(2)
