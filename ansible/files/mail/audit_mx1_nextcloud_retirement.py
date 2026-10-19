#!/usr/bin/env python3
"""Categorical read-only inventory of the retiring Nextcloud on MX1.

Only sanitized categories are emitted. No config contents, documents, account
names, DB rows, credentials, cert private keys or inventory IPs are printed.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

EXPECTED = sys.argv[1]
ROOT = Path(sys.argv[2])
HOST = "mx1-nextcloud-retirement-audit"


def inspect(argv, timeout=25):
    try:
        return subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False, text=True
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def output(args, timeout=25):
    result = inspect(args, timeout=timeout)
    return result.stdout if result is not None and result.returncode == 0 else None


def state(unit):
    result = inspect(["systemctl", "is-active", unit])
    if result is None:
        return "UNKNOWN"
    value = result.stdout.strip()
    return value if value in ("active", "inactive", "failed", "activating", "deactivating") else "OTHER"


def occurrence_in_crontab(user):
    result = inspect(["crontab", "-u", user, "-l"])
    if result is None:
        return "UNKNOWN"
    if result.returncode:
        return "NO_CRONTAB_OR_INACCESSIBLE"
    active = [line.strip() for line in result.stdout.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    matches = [line for line in active if re.search(r"cron[.]php|/occ\b", line)]
    return len(matches)


def size(root):
    if not root.is_dir() or root.is_symlink():
        return "ABSENT_OR_UNSAFE"
    found = output(["du", "-sh", "--", str(root)], timeout=180)
    return found.split()[0] if found else "UNAVAILABLE"


actual = output(["hostname", "-f"])
if actual is None or actual.strip() != EXPECTED:
    print("AUDIT_REJECTED_WRONG_HOST")
    sys.exit(2)
if str(ROOT) != "/usr/share/nginx/de.tbergen.cloud/html":
    print("AUDIT_REJECTED_UNREVIEWED_ROOT")
    sys.exit(2)

report = {
    "identity": "VERIFIED",
    "mode": "READ_ONLY",
    "nextcloud_code_present": (ROOT / "occ").is_file(),
    "nextcloud_config_present": (ROOT / "config/config.php").is_file(),
    "nextcloud_data": size(ROOT / "data"),
    "nextcloud_tree": size(ROOT),
    "apache_nextcloud_cron_entries": occurrence_in_crontab("apache"),
    "root_nextcloud_cron_entries": occurrence_in_crontab("root"),
    "nginx_service": state("nginx"),
    "php_fpm_service": state("php-fpm"),
    "mariadb_service": state("mariadb"),
    "postfix_service": state("postfix"),
    "dovecot_service": state("dovecot"),
}
if (ROOT / "occ").is_file() and not (ROOT / "occ").is_symlink():
    raw = output(
        ["runuser", "-u", "apache", "--", "php", str(ROOT / "occ"), "status"],
        timeout=45,
    )
    if raw is None:
        report["nextcloud_occ_status"] = "UNAVAILABLE"
    else:
        fields = {}
        for line in raw.splitlines():
            found = re.match(r"\s*-\s*(installed|version|maintenance|needsDbUpgrade):\s*(\S+)", line)
            if found:
                fields[found.group(1)] = found.group(2)
        report["nextcloud_occ_status"] = fields
else:
    report["nextcloud_occ_status"] = "ABSENT"

db = output(["mariadb", "--protocol=socket", "--batch", "--skip-column-names",
             "-e", "SELECT COUNT(*) FROM information_schema.SCHEMATA "
                   "WHERE SCHEMA_NAME='nextcloud'"], timeout=20)
if db is None:
    report["nextcloud_database"] = "ACCESS_UNAVAILABLE"
else:
    report["nextcloud_database"] = (
        "PRESENT" if db.strip() == "1" else
        "ABSENT" if db.strip() == "0" else "UNEXPECTED_RESULT"
    )

nginx = inspect(["nginx", "-T"], timeout=30)
if nginx is None or nginx.returncode != 0:
    report["nginx_config"] = "UNAVAILABLE_OR_INVALID"
else:
    text = nginx.stdout
    report["nginx_config"] = "VALID"
    report["nginx_cloud_references"] = len(re.findall(r"cloud[.]tbergen[.]de", text, re.I))
    report["nginx_cloud_server_name"] = bool(re.search(
        r"(?m)^\s*server_name\s+[^;]*\bcloud[.]tbergen[.]de\b", text, re.I))
    report["nginx_office_references"] = len(re.findall(r"office[.]tbergen[.]de", text, re.I))

paths = [Path("/etc/nginx/conf.d"), Path("/etc/nginx/sites-available"),
         Path("/etc/nginx/sites-enabled")]
report["cloud_vhost_candidates"] = sum(
    1 for folder in paths if folder.is_dir()
    for item in folder.iterdir()
    if "cloud" in item.name.lower() or "nextcloud" in item.name.lower()
)

p = inspect(["podman", "ps", "-a", "--format", "{{.Names}}"], timeout=30)
report["collabora_container_count"] = (
    "UNKNOWN" if p is None or p.returncode != 0 else
    sum("collabora" in line.lower() for line in p.stdout.splitlines())
)
mounts = output(["findmnt", "-rn", "-o", "TARGET"], timeout=20)
report["nested_nextcloud_mount_count"] = (
    "UNKNOWN" if mounts is None else
    sum(line.startswith(str(ROOT) + "/") for line in mounts.splitlines())
)

print(json.dumps({HOST: report}, sort_keys=True, ensure_ascii=True))
print("MX1_NEXTCLOUD_RETIREMENT_READ_ONLY=COMPLETE")
