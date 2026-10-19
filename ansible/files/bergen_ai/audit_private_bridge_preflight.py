#!/usr/bin/env python3
"""Read-only preflight for a proposed isolated Bergen-AI Linux bridge.

Never modifies PVE, network interfaces, LXC, firewall, Ollama or Paperless.
Does not send network traffic, log actual IPs/bridges/routes or touch model data.
Output deliberately reports classifications, not an implementation approval.
Candidate is proposal-only; route checks cover only the host and LXC110/126/120.
"""
import ipaddress
import json
from pathlib import Path
import re
import subprocess

FRAME = "BERGEN_AI_PRIVATE_BRIDGE_PREFLIGHT_V1:"
BRIDGE = "vmbr10"
CANDIDATE = ipaddress.ip_network("172.30.110.0/28")
GUESTS = (("110", "bergen-ai"), ("126", "bergen-paperless"), ("120", "bergen-syslog"))
MAX_BYTES = 180000


def read_command(argv, max_bytes=MAX_BYTES, timeout=12):
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout,
                           check=False)
        if p.returncode or len(p.stdout) > max_bytes:
            return None
        return p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def json_command(argv):
    raw = read_command(argv)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except (ValueError, TypeError):
        return None


def single_ct_identity(vmid, hostname):
    raw = read_command(["pct", "config", vmid], max_bytes=24000)
    status = read_command(["pct", "status", vmid], max_bytes=200)
    if (not raw or f"hostname: {hostname}" not in raw.splitlines()
        or "unprivileged: 1" not in raw.splitlines()
        or "lxc.apparmor.profile: unconfined" in raw.splitlines()
        or not status or status.strip() != "status: running"):
        return None
    network_lines = [line for line in raw.splitlines()
                     if re.match(r"^net[0-9]+:\s", line)]
    return len(network_lines)


def kernel_bridge_exists():
    raw = read_command(["ip", "-j", "link", "show"], max_bytes=MAX_BYTES)
    if raw is None:
        return "UNVERIFIED"
    try:
        links = json.loads(raw)
        if not isinstance(links, list):
            return "UNVERIFIED"
        return "EXISTS" if any(isinstance(x, dict) and
                               x.get("ifname") == BRIDGE for x in links) else "ABSENT"
    except (ValueError, TypeError):
        return "UNVERIFIED"


def config_bridge_exists():
    files = [Path("/etc/network/interfaces")]
    directory = Path("/etc/network/interfaces.d")
    try:
        if directory.exists():
            files += sorted(p for p in directory.iterdir() if p.is_file())
        if not files[0].is_file():
            return "UNVERIFIED"
        for file in files:
            if file.is_symlink():
                return "UNVERIFIED"
            if file.stat().st_size > 180000:
                return "UNVERIFIED"
            value = file.read_text(encoding="utf-8")
            # Strictly match interface declarations; do not expose content.
            if re.search(r"(?m)^\s*(?:auto|allow-hotplug|iface)\s+" +
                         re.escape(BRIDGE) + r"(?:\s|$)", value):
                return "EXISTS"
        return "ABSENT"
    except (OSError, UnicodeError):
        return "UNVERIFIED"


def any_guest_references_bridge():
    roots = [Path("/etc/pve/lxc"), Path("/etc/pve/nodes")]
    try:
        if not all(d.is_dir() for d in roots):
            return "UNVERIFIED"
        files = list(roots[0].glob("*.conf"))
        files += list(roots[1].glob("*/qemu-server/*.conf"))
        if len(files) > 2000:
            return "UNVERIFIED"
        pattern = re.compile(r"(?m)(?:^|,)bridge=" + re.escape(BRIDGE) +
                             r"(?:,|$)")
        for file in files:
            if file.is_symlink() or file.stat().st_size > 150000:
                return "UNVERIFIED"
            if pattern.search(file.read_text(encoding="utf-8")):
                return "IN_USE"
        return "NOT_REFERENCED_IN_SCANNED_GUESTS"
    except (OSError, UnicodeError):
        return "UNVERIFIED"


def network_overlaps(addrs, routes):
    """Return True/False only for known addr/route information."""
    if not isinstance(addrs, list) or not isinstance(routes, list):
        return None
    try:
        for iface in addrs:
            for row in iface.get("addr_info", []):
                if row.get("family") != "inet":
                    continue
                address = row.get("local")
                prefix = row.get("prefixlen")
                if not address or not isinstance(prefix, int):
                    return None
                item = ipaddress.ip_interface(f"{address}/{prefix}")
                if item.network.overlaps(CANDIDATE):
                    return True
        for route in routes:
            dst = route.get("dst")
            if not isinstance(dst, str):
                return None
            if dst == "default":
                continue
            try:
                subnet = ipaddress.ip_network(dst, strict=False)
            except ValueError:
                continue
            if subnet.version == 4 and subnet.overlaps(CANDIDATE):
                return True
        return False
    except (ValueError, TypeError, AttributeError):
        return None


def guest_routes(vmid):
    command = ["pct", "exec", vmid, "--", "ip", "-j", "-4"]
    a = json_command(command + ["address", "show"])
    r = json_command(command + ["route", "show", "table", "all"])
    return network_overlaps(a, r)


def host_routes():
    a = json_command(["ip", "-j", "-4", "address", "show"])
    r = json_command(["ip", "-j", "-4", "route", "show", "table", "all"])
    return network_overlaps(a, r)


def classification(results):
    if any(v is None for v in results):
        return "UNVERIFIED"
    return "OVERLAP_FOUND" if any(results) else "NO_OVERLAP_IN_SCOPED_ROUTES"


def emit(**data):
    print(FRAME + json.dumps(dict(
        AUDIT="READ_ONLY", CHANGED=False, BRIDGE_CANDIDATE="vmbr10",
        SUBNET_CANDIDATE="PROPOSAL_ONLY_172.30.110.0_28",
        PRIVATE_NET_DESIGN="NO_UPLINK_NO_HOST_IP_NO_DEFAULT_GATEWAY",
        NETWORK_CHANGES="NONE", FIREWALL_CHANGES="NONE",
        OLLAMA_BINDING_CHANGED="NO", PAPERLESS_CHANGED="NO",
        GUEST_INTERFACE_CHANGES="NONE", SUBNET_CLEARANCE="NOT_PROVEN",
        APPLY_AUTHORIZED=False, **data
    ), sort_keys=True), flush=True)


def main():
    count = {}
    for vmid, hostname in GUESTS:
        value = single_ct_identity(vmid, hostname)
        if value is None:
            emit(STATUS="GUEST_IDENTITY_OR_STATE_UNVERIFIED",
                 CT110_NICS="UNVERIFIED", CT126_NICS="UNVERIFIED",
                 CT120_NICS="UNVERIFIED", BRIDGE_KERNEL="UNVERIFIED",
                 BRIDGE_CONFIG="UNVERIFIED", BRIDGE_GUEST_REFERENCES="UNVERIFIED",
                 SCOPED_IPV4_ROUTE_OVERLAP="UNVERIFIED")
            return
        count[vmid] = value

    kernel = kernel_bridge_exists()
    config = config_bridge_exists()
    refs = any_guest_references_bridge()
    overlap = classification([host_routes()] +
                             [guest_routes(vmid) for vmid, _ in GUESTS])
    if "UNVERIFIED" in (kernel, config, refs, overlap):
        status = "REVIEW_INCOMPLETE"
    elif kernel == "ABSENT" and config == "ABSENT" and refs == "NOT_REFERENCED_IN_SCANNED_GUESTS" and overlap == "NO_OVERLAP_IN_SCOPED_ROUTES":
        status = "CANDIDATE_LOCALLY_UNCONFLICTED"
    else:
        status = "REVIEW_EXISTING_NETWORK_CONFLICT"
    emit(STATUS=status, CT110_NICS=count["110"], CT126_NICS=count["126"],
         CT120_NICS=count["120"], BRIDGE_KERNEL=kernel,
         BRIDGE_CONFIG=config, BRIDGE_GUEST_REFERENCES=refs,
         SCOPED_IPV4_ROUTE_OVERLAP=overlap,
         IPV6_DESIGN="NOT_CONFIGURED_IN_PROPOSAL",
         PROXMOX_APPLY_GATE="BLOCKED_PENDING_REVIEW",
         INFERENCE_API_ACCESS_GATE="BLOCKED_PENDING_RESTRICTED_BIND_AND_TEST")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED", CT110_NICS="UNVERIFIED",
             CT126_NICS="UNVERIFIED", CT120_NICS="UNVERIFIED",
             BRIDGE_KERNEL="UNVERIFIED", BRIDGE_CONFIG="UNVERIFIED",
             BRIDGE_GUEST_REFERENCES="UNVERIFIED",
             SCOPED_IPV4_ROUTE_OVERLAP="UNVERIFIED")
