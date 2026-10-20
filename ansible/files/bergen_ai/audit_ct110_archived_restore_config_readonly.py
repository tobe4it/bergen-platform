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


def sensitive_categories(values):
    """Count each sensitive directive key once, never emit key/value pairs.

    Original v1 count double-counted some lxc.* keys because they were both
    in DANGEROUS and in the unknown-lxc catch-all. Preserve that older
    metric for comparison while providing precise non-overlapping classes.
    No category grants permission for a restore.
    """
    keys = list(values)
    explicit = {k for k in keys if k in DANGEROUS}
    lxc = {k for k in keys if k.startswith("lxc.") and k != "lxc.mount.entry"}
    pve_device = {k for k in keys if re.fullmatch(r"dev[0-9]+", k)}
    sensitive = explicit | lxc | pve_device
    categories = {
        "HOOK": set(),
        "APPARMOR": set(),
        "LXC_MOUNT_POLICY": set(),
        "CGROUP_DEVICE_POLICY": set(),
        "CAPABILITY_POLICY": set(),
        "ID_MAPPING": set(),
        "LXC_NETWORK": set(),
        "PVE_DEVICE": set(),
        "OTHER_LXC": set(),
        "OTHER": set(),
    }
    for k in sensitive:
        if k == "hookscript" or k.startswith("lxc.hook."):
            kind = "HOOK"
        elif k.startswith("lxc.apparmor."):
            kind = "APPARMOR"
        elif k.startswith("lxc.mount."):
            kind = "LXC_MOUNT_POLICY"
        elif k.startswith("lxc.cgroup."):
            kind = "CGROUP_DEVICE_POLICY"
        elif k.startswith("lxc.cgroup2."):
            kind = "CGROUP_DEVICE_POLICY"
        elif k.startswith("lxc.cap."):
            kind = "CAPABILITY_POLICY"
        elif k.startswith("lxc.idmap"):
            kind = "ID_MAPPING"
        elif k.startswith("lxc.net."):
            kind = "LXC_NETWORK"
        elif k in pve_device:
            kind = "PVE_DEVICE"
        elif k.startswith("lxc."):
            kind = "OTHER_LXC"
        else:
            kind = "OTHER"
        categories[kind].add(k)
    out = {f"SENSITIVE_{kind}_COUNT": len(members)
           for kind, members in categories.items()}
    out["SENSITIVE_UNIQUE_COUNT"] = len(sensitive)
    out["SENSITIVE_DUPLICATE_OVERCOUNT"] = (
        len(explicit) + len(lxc) + len(pve_device) - len(sensitive))
    return out


def device_type(value):
    """Categorize the host device name without exporting path or properties."""
    if not isinstance(value, str) or len(value) > 2048:
        return "UNVERIFIED"
    path = value.split(",", 1)[0].strip()
    if re.fullmatch(r"/dev/dri/renderD[0-9]+", path):
        return "GPU_RENDER"
    if re.fullmatch(r"/dev/dri/card[0-9]+", path):
        return "GPU_CARD"
    if path == "/dev/kfd":
        return "GPU_KFD"
    if re.fullmatch(r"/dev/video[0-9]+", path):
        return "VIDEO"
    if path.startswith("/dev/bus/usb/") or re.fullmatch(
            r"/dev/(?:ttyUSB|ttyACM)[0-9]+", path):
        return "USB"
    if path == "/dev/net/tun":
        return "TUN"
    if path == "/dev/fuse":
        return "FUSE"
    if path.startswith("/dev/"):
        return "OTHER_DEVICE"
    return "UNRECOGNIZED_FORMAT"


def cgroup_device_rule(value):
    """Return only device *class* and scope, never major/minor/access tokens."""
    if not isinstance(value, str):
        return ("UNVERIFIED", "UNVERIFIED")
    # LXC device policy follows a <type> <major>:<minor> <permissions> form.
    match = re.fullmatch(r"([abc])\s+(\*|[0-9]+):(\*|[0-9]+)\s+([rwm]{1,3})", value.strip())
    if match is None or len(set(match.group(4))) != len(match.group(4)):
        return ("OTHER_RULE_FORMAT", "UNVERIFIED")
    dev_type, major, minor, _ = match.groups()
    if dev_type == "a" or major == "*":
        return ("BROAD_ALL_DEVICES", "UNRESTRICTED_MAJOR")
    if dev_type != "c":
        return ("OTHER_BLOCK_OR_TYPE", "ALL_MINORS" if minor == "*" else "SINGLE_MINOR")
    if major == "226":
        kind = "DRM"
    elif major == "10" and minor == "229":
        kind = "FUSE"
    elif major == "10" and minor == "200":
        kind = "TUN"
    elif major == "189":
        kind = "USB"
    elif major == "235":
        kind = "ACCELERATOR_POSSIBLE"
    else:
        kind = "OTHER_CHAR_MAJOR"
    return (kind, "ALL_MINORS" if minor == "*" else "SINGLE_MINOR")


def device_details(values):
    if values is None:
        return dict(DEV0_CLASS="UNVERIFIED", DEV1_CLASS="UNVERIFIED",
                    PVE_DEVICE_INDEX_PROFILE="UNVERIFIED",
                    CGROUP_DEVICE_RULE_CLASS="UNVERIFIED",
                    CGROUP_DEVICE_RULE_SCOPE="UNVERIFIED")
    indices = sorted(k for k in values if re.fullmatch(r"dev[0-9]+", k))
    index_class = "EXACT_DEV0_DEV1" if indices == ["dev0", "dev1"] else (
        "NO_PVE_DEVICES" if not indices else "OTHER_DEVICE_INDICES")
    rule_keys = [k for k in values if k in (
        "lxc.cgroup.devices.allow", "lxc.cgroup2.devices.allow",
        "lxc.cgroup.devices.deny", "lxc.cgroup2.devices.deny")]
    if len(rule_keys) == 1 and len(values[rule_keys[0]]) == 1:
        rule_class, rule_scope = cgroup_device_rule(values[rule_keys[0]][0])
    else:
        rule_class, rule_scope = ("NONE" if not rule_keys else "OTHER_OR_MULTIPLE", "UNVERIFIED")
    return dict(
        DEV0_CLASS=device_type(one(values, "dev0")) if "dev0" in values else "ABSENT",
        DEV1_CLASS=device_type(one(values, "dev1")) if "dev1" in values else "ABSENT",
        PVE_DEVICE_INDEX_PROFILE=index_class,
        CGROUP_DEVICE_RULE_CLASS=rule_class,
        CGROUP_DEVICE_RULE_SCOPE=rule_scope)


def profile(values):
    if values is None:
        fields = {f"SENSITIVE_{kind}_COUNT": "UNVERIFIED"
                  for kind in (
                      "HOOK", "APPARMOR", "LXC_MOUNT_POLICY",
                      "CGROUP_DEVICE_POLICY", "CAPABILITY_POLICY",
                      "ID_MAPPING", "LXC_NETWORK", "PVE_DEVICE",
                      "OTHER_LXC", "OTHER")}
        fields["SENSITIVE_UNIQUE_COUNT"] = "UNVERIFIED"
        fields["SENSITIVE_DUPLICATE_OVERCOUNT"] = "UNVERIFIED"
        return dict(CONFIG_READ="UNVERIFIED", NETWORK_INTERFACE_COUNT="UNVERIFIED",
                    ONBOOT="UNVERIFIED", EXTERNAL_MP_COUNT="UNVERIFIED",
                    DEVICE_MOUNT_PROFILE="UNVERIFIED",
                    DANGEROUS_CONFIG_DIRECTIVES="UNVERIFIED",
                    SOURCE_HOSTNAME="UNVERIFIED",
                    SOURCE_ROOTFS="UNVERIFIED", SOURCE_UNPRIVILEGED="UNVERIFIED",
                    STATUS="UNVERIFIED", **fields, **device_details(None))
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
        **sensitive_categories(values),
        **device_details(values),
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
