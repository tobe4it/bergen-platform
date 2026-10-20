#!/usr/bin/env python3
"""Inspect CT110 vzdump *configuration* only. Never restore or extract guest files.

The raw Proxmox config can include private IPs, addresses and device paths.
It stays in-process and in a no_log Ansible task; only fixed status categories
and bounded counts are emitted. This is not an authorization to run pct restore.
"""
import json
import re
import shlex
import subprocess

FRAME = "BERGEN_AI_CT110_RESTORE_CONFIG_AUDIT_V1:"
STORAGE = "bergen-synology-backup"
PREFIX = STORAGE + ":backup/"
ARCHIVE = re.compile(r"vzdump-lxc-110-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.tar\.zst")
KEY = re.compile(r"[a-z][a-z0-9_.-]{0,70}")
MAX_CONFIG_BYTES = 65536
DANGEROUS = {
    "hookscript", "lxc.hook.pre-start", "lxc.hook.start",
    "lxc.hook.post-stop", "lxc.apparmor.profile",
    "lxc.mount.auto", "lxc.net.0.type",
}


def run(argv, maximum=1200000, timeout=30):
    try:
        p = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
        if p.returncode or len(p.stdout) > maximum:
            return None
        return p.stdout.decode("utf-8", "strict")
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def backup_volid():
    raw = run([
        "pvesh", "get", f"/nodes/venombox/storage/{STORAGE}/content",
        "--content", "backup", "--output-format", "json"])
    try:
        rows = json.loads(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if not isinstance(rows, list) or len(rows) > 10000:
        return None
    matches = []
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("volid"), str):
            return None
        volid = item["volid"]
        if re.search(r"(?:/|:)vzdump-lxc-110-", volid):
            matches.append(item)
    if len(matches) != 1:
        return None
    item = matches[0]
    volid = item["volid"]
    if (not volid.startswith(PREFIX)
            or ARCHIVE.fullmatch(volid[len(PREFIX):]) is None
            or type(item.get("size")) is not int or item["size"] <= 0):
        return None
    return volid


def parse_config(raw):
    if not isinstance(raw, str) or not 0 < len(raw) < MAX_CONFIG_BYTES:
        return None
    lines = raw.splitlines()
    if not 1 <= len(lines) <= 220:
        return None
    values = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if ":" not in line or "\x00" in line:
            return None
        k, v = line.split(":", 1)
        if KEY.fullmatch(k) is None or not v.strip() or len(v) > 8192:
            return None
        values.setdefault(k, []).append(v.strip())
    return values if values else None


def one(values, key):
    lst = values.get(key, [])
    return lst[0] if len(lst) == 1 else None


def fuse_only(values):
    entries = values.get("lxc.mount.entry", [])
    if len(entries) != 1:
        return False
    try:
        parts = shlex.split(entries[0])
    except ValueError:
        return False
    if len(parts) not in (4, 6):
        return False
    if parts[0] != "/dev/fuse" or "/" + parts[1].lstrip("/") != "/dev/fuse":
        return False
    if parts[2] != "none" or (len(parts) == 6 and parts[4:] != ["0", "0"]):
        return False
    opts = parts[3].split(",")
    return (len(opts) == len(set(opts))
            and all(x in {"bind", "optional", "create=file", "ro"} for x in opts)
            and "bind" in opts and "create=file" in opts)


def profile(values):
    if values is None:
        return dict(CONFIG_READ="UNVERIFIED", NETWORK_INTERFACE_COUNT="UNVERIFIED",
                    ONBOOT="UNVERIFIED", EXTERNAL_MP_COUNT="UNVERIFIED",
                    DEVICE_MOUNT_PROFILE="UNVERIFIED",
                    DANGEROUS_CONFIG_DIRECTIVES="UNVERIFIED",
                    SOURCE_HOSTNAME="UNVERIFIED",
                    SOURCE_ROOTFS="UNVERIFIED", SOURCE_UNPRIVILEGED="UNVERIFIED",
                    STATUS="UNVERIFIED")
    keys = list(values)
    networks = [k for k in keys if re.fullmatch(r"net[0-9]+", k)]
    mounts = [k for k in keys if re.fullmatch(r"mp[0-9]+", k)]
    unknown_lxc = [
        k for k in keys if k.startswith("lxc.")
        and k != "lxc.mount.entry"
    ]
    sensitive = (
        [k for k in keys if k in DANGEROUS]
        + unknown_lxc
        + [k for k in keys if k.startswith("dev") and re.fullmatch(r"dev[0-9]+", k)]
    )
    duplicates = any(len(x) != 1 for x in values.values())
    onboot = one(values, "onboot")
    boot = (
        "ENABLED" if onboot == "1" else
        "DISABLED" if onboot == "0" else
        "ABSENT" if onboot is None and "onboot" not in values else
        "OTHER"
    )
    root = one(values, "rootfs")
    root_expected = bool(
        root and re.fullmatch(r"local-zfs:[^,\s]+(?:,[^\r\n]*)?", root)
    )
    hostname = one(values, "hostname")
    unpriv = one(values, "unprivileged")
    count = sum(len(values[k]) for k in networks)
    mpcount = sum(len(values[k]) for k in mounts)
    safe = bool(
        not duplicates and count == 1 and mpcount == 0
        and boot in ("ENABLED", "DISABLED", "ABSENT", "OTHER")
        and root_expected and hostname == "bergen-ai" and unpriv == "1"
        and len(sensitive) == 0 and fuse_only(values)
        and len(values) <= 110
    )
    return dict(
        CONFIG_READ="PARSED",
        NETWORK_INTERFACE_COUNT=count,
        ONBOOT=boot,
        EXTERNAL_MP_COUNT=mpcount,
        DEVICE_MOUNT_PROFILE="EXACT_FUSE_DEVICE_ONLY" if fuse_only(values)
                             else "UNKNOWN_OR_EXTRA_DEVICE",
        DANGEROUS_CONFIG_DIRECTIVES=len(sensitive),
        SOURCE_HOSTNAME="EXPECTED_ORIGINAL" if hostname == "bergen-ai"
                        else "OTHER_OR_MISSING",
        SOURCE_ROOTFS="EXPECTED_LOCAL_ZFS" if root_expected
                      else "OTHER_OR_MISSING",
        SOURCE_UNPRIVILEGED="YES" if unpriv == "1" else "NO_OR_UNVERIFIED",
        STATUS="KNOWN_SOURCE_CONFIGURATION" if safe else "REVIEW_REQUIRED",
    )


def report():
    volid = backup_volid()
    if volid is None:
        details = profile(None)
        archive_status = "UNVERIFIED"
    else:
        # Supported Proxmox command reads just the stored config; not a guest
        # filesystem extraction. Output is classified, never printed.
        raw = run(["pvesm", "extractconfig", volid],
                  maximum=MAX_CONFIG_BYTES, timeout=120)
        details = profile(parse_config(raw))
        archive_status = "ONE_EXACT_BACKUP_CONFIG_SELECTED"
    return dict(
        AUDIT="READ_ONLY", CHANGED=False,
        ARCHIVE_SELECTION=archive_status, **details,
        ORIGINAL_NETWORK_CONFIG_PRESERVED_IN_ARCHIVE="NOT_EXPORTED",
        RESTORE_CONFIG_OVERRIDE_PROVEN=False,
        NETWORK_ISOLATION="NOT_PROVEN",
        GUEST_START_POLICY="NOT_PROVEN",
        RESTORE_EXECUTED=False, RESTORE_AUTHORIZED=False,
        GUEST_CREATED=False, GUEST_STARTED=False,
        RESTORE_TEST="NOT_ATTESTED", ROLLBACK_CLEARANCE="NOT_PROVEN",
        NETWORK_CHANGES="NONE", APPLY_AUTHORIZED=False,
    )


def main():
    try:
        value = report()
    except Exception:
        value = dict(
            AUDIT="READ_ONLY", CHANGED=False, ARCHIVE_SELECTION="UNVERIFIED",
            **profile(None), ORIGINAL_NETWORK_CONFIG_PRESERVED_IN_ARCHIVE="NOT_EXPORTED",
            RESTORE_CONFIG_OVERRIDE_PROVEN=False,
            NETWORK_ISOLATION="NOT_PROVEN", GUEST_START_POLICY="NOT_PROVEN",
            RESTORE_EXECUTED=False, RESTORE_AUTHORIZED=False,
            GUEST_CREATED=False, GUEST_STARTED=False, RESTORE_TEST="NOT_ATTESTED",
            ROLLBACK_CLEARANCE="NOT_PROVEN", NETWORK_CHANGES="NONE",
            APPLY_AUTHORIZED=False)
    print(FRAME + json.dumps(value, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
