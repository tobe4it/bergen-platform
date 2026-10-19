#!/usr/bin/env python3
"""Read-only, fail-closed external-IPAM and Proxmox rollback evidence audit.

Runs in two explicit modes. The controller's local JSON is operator-supplied;
it is NOT a direct UniFi/VPN API query and cannot prove completeness. Host
inspection never modifies, sends packets, or publishes addresses/keys.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

CANDIDATE = ipaddress.ip_network("172.30.110.0/28")
FRAME = "BERGEN_AI_PRIVATE_BRIDGE_GATES_V1:"
SCOPES = ("unifi", "vpn", "other_hosts")
BACKUP_ROOT = Path("/mnt/pve/bergen-synology-backup")
EXPECTED = (("110", "bergen-ai"), ("126", "bergen-paperless"))


def emit(mode, **fields):
    result = dict(AUDIT="READ_ONLY", CHANGED=False, MODE=mode,
                  APPLY_AUTHORIZED=False, FULL_NETWORK_CLEARANCE="NOT_PROVEN",
                  ROLLBACK_CLEARANCE="NOT_PROVEN", NETWORK_CHANGES="NONE",
                  BRIDGE_CANDIDATE="vmbr90",
                  SUBNET_CANDIDATE="172.30.110.0/28")
    result.update(fields)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


def parse_cidr(value):
    if not isinstance(value, str) or len(value) > 80 or "/" not in value:
        return None
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        return None


def audit_manifest(data):
    if not isinstance(data, dict) or set(data) != {"scopes"}:
        return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    scopes = data["scopes"]
    if not isinstance(scopes, dict) or set(scopes) != set(SCOPES):
        return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    overlap = False
    catchall = False
    complete = True
    for name in SCOPES:
        item = scopes[name]
        if (not isinstance(item, dict) or set(item) != {"complete", "networks"}
                or type(item["complete"]) is not bool
                or not isinstance(item["networks"], list)
                or len(item["networks"]) > 256):
            return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
        complete &= item["complete"]
        for value in item["networks"]:
            network = parse_cidr(value)
            if network is None:
                return ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
            if network.version != 4:
                continue
            if network.prefixlen == 0:
                catchall = True  # 0/0 AllowedIPs is not proof of subnet ownership.
            elif network.overlaps(CANDIDATE):
                overlap = True
    status = ("OVERLAP_FOUND" if overlap else
              "VPN_CATCHALL_REVIEW" if catchall else
              "NO_OVERLAP_IN_DECLARED_RANGES")
    coverage = ("OPERATOR_DECLARED_COMPLETE" if complete else
                "OPERATOR_DECLARED_INCOMPLETE")
    return status, coverage, "MANUAL_INPUT_NOT_INDEPENDENTLY_VERIFIED"


def run_ipam(path):
    try:
        p = Path(path)
        s = p.lstat()
        if (not stat.S_ISREG(s.st_mode) or s.st_size > 65536
                or (s.st_mode & 0o077) != 0):
            raise ValueError("Unsafe local inventory")
        data = json.loads(p.read_text(encoding="utf-8"))
        status, coverage, quality = audit_manifest(data)
    except (OSError, ValueError, UnicodeError, TypeError):
        status, coverage, quality = ("UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    emit("IPAM", STATUS=status, SCOPE_COVERAGE=coverage,
         SOURCE_QUALITY=quality, UNIFI_API="NOT_QUERIED",
         REMOTE_VPN_API="NOT_QUERIED", NEXT_ACTION="VERIFY_DECLARED_SCOPE_WITH_OPERATOR")


def command(argv, timeout=8, limit=40000):
    try:
        p = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
        if p.returncode or len(p.stdout) > limit:
            return None
        return p.stdout.decode("utf-8", "strict")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def safe_existing(path, directory=False):
    try:
        meta = path.lstat()
        return (stat.S_ISDIR(meta.st_mode) if directory else
                stat.S_ISREG(meta.st_mode)) and not path.is_symlink()
    except OSError:
        return False


def config_sources():
    base = Path("/etc/network/interfaces")
    extra = Path("/etc/network/interfaces.d")
    if not safe_existing(base) or not safe_existing(extra, directory=True):
        return "UNVERIFIED"
    try:
        files = list(extra.iterdir())
        if len(files) > 100:
            return "UNVERIFIED"
        for path in [base] + files:
            if not safe_existing(path) or path.stat().st_size > 200000:
                return "UNVERIFIED"
            with path.open("rb") as stream:
                stream.read(1)
        return "READABLE_SOURCE_ONLY"
    except OSError:
        return "UNVERIFIED"


def guest_config(vmid, expected_hostname):
    raw = command(["pct", "config", vmid])
    if raw is None:
        return "UNVERIFIED"
    lines = raw.splitlines()
    if (f"hostname: {expected_hostname}" not in lines
            or not any(re.match(r"^net0:\s", line) for line in lines)):
        return "UNVERIFIED"
    return "READABLE_SOURCE_ONLY"


def backup_metadata(vmid):
    # Scans only the already known NFS dump location, not backup payloads.
    dump = BACKUP_ROOT / "dump"
    if not safe_existing(dump, directory=True):
        return "UNVERIFIED"
    try:
        matches = list(dump.glob(f"vzdump-lxc-{vmid}-*.tar.*"))
        if len(matches) > 200:
            return "UNVERIFIED"
        recent = False
        for path in matches:
            if not safe_existing(path):
                continue
            info = path.stat()
            if info.st_size > 0 and 0 <= time.time() - info.st_mtime <= 7 * 86400:
                recent = True
        return "RECENT_FILE_METADATA_ONLY" if recent else "NO_RECENT_FILE_METADATA"
    except OSError:
        return "UNVERIFIED"


def backup_mount():
    # Exact mountpoint is required; a plain directory is not a backup proof.
    raw = command(["findmnt", "-J", "-M", str(BACKUP_ROOT)])
    try:
        fs = json.loads(raw)["filesystems"]
        if (len(fs) != 1 or fs[0].get("target") != str(BACKUP_ROOT)
                or fs[0].get("fstype") not in ("nfs", "nfs4")):
            return "UNVERIFIED"
        return "NFS_MOUNT_PRESENT_ONLY"
    except (ValueError, TypeError, KeyError):
        return "UNVERIFIED"


def local_wg_allowed_ips():
    if shutil.which("wg") is None:
        return "WG_TOOL_NOT_INSTALLED_ON_PVE"
    raw = command(["wg", "show", "all", "allowed-ips"])
    if raw is None:
        return "UNVERIFIED"
    overlap = False
    catchall = False
    for line in raw.splitlines():
        columns = line.split(None, 2)
        if len(columns) != 3:
            return "UNVERIFIED"
        for value in columns[2].replace(",", " ").split():
            if value == "(none)":
                continue
            network = parse_cidr(value)
            if network is None:
                return "UNVERIFIED"
            if network.version == 4:
                if network.prefixlen == 0:
                    catchall = True
                elif network.overlaps(CANDIDATE):
                    overlap = True
    return ("OVERLAP_FOUND" if overlap else
            "LOCAL_CATCHALL_REVIEW" if catchall else
            "NO_OVERLAP_IN_LOCAL_WG_ALLOWED_IPS")


def run_host():
    net = config_sources()
    ct110 = guest_config(*EXPECTED[0])
    ct126 = guest_config(*EXPECTED[1])
    mount = backup_mount()
    b110 = backup_metadata("110") if mount == "NFS_MOUNT_PRESENT_ONLY" else "UNVERIFIED"
    b126 = backup_metadata("126") if mount == "NFS_MOUNT_PRESENT_ONLY" else "UNVERIFIED"
    wg = local_wg_allowed_ips()
    emit("HOST", STATUS=("REVIEW_INCOMPLETE" if "UNVERIFIED" in
         (net, ct110, ct126, mount, b110, b126, wg) else "EVIDENCE_PARTIAL"),
         HOST_NETWORK_CONFIG=net, CT110_CONFIG=ct110, CT126_CONFIG=ct126,
         BACKUP_MOUNT=mount, CT110_BACKUP=b110, CT126_BACKUP=b126,
         PVE_LOCAL_WG=wg, CONFIG_BACKUP="NOT_ATTESTED",
         OLLAMA_WEBUI_CONFIG_BACKUP="NOT_ATTESTED",
         RESTORE_TEST="NOT_ATTESTED", OOB_CONSOLE="NOT_ATTESTED",
         NEXT_ACTION="VERIFY_BACKUP_CONTENT_RESTORE_AND_OOB_ACCESS")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "ipam" and len(sys.argv) == 3:
        run_ipam(sys.argv[2])
    elif sys.argv[1:] == ["host"]:
        run_host()
    else:
        emit("INVALID", STATUS="UNVERIFIED", NEXT_ACTION="CHECK_AUDIT_ARGS")
