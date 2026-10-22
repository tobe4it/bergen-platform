#!/usr/bin/env python3
"""Inventory additional PVE/Podman/Docker IPv4 collision signals, read-only.

Static PVE LXC assignments, all RUNNING LXC addr/routes, and container
network definitions on known AI/Paperless guests are scoped. Also check
Docker on venombox if available. No modifying operations, network packets,
secrets, addresses, or network names in the exported audit frame.

Cannot certify UniFi, remote VPNs, offline/dynamic guest IPs, QEMU guest
networks or all application-specific overlays. Always fail closed for apply.
"""
import ipaddress
import json
import re
import shutil
import subprocess

CANDIDATE = ipaddress.ip_network("172.30.110.0/28")
FRAME = "BERGEN_AI_PRIVATE_BRIDGE_EXTENDED_V1:"
GUEST_MAX = 80
NETWORK_MAX = 100
TARGETS = ("110", "126")


def run(argv, max_output=250000, timeout=9):
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        if p.returncode != 0 or len(p.stdout) > max_output:
            return None
        return p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def obj(argv):
    raw = run(argv)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def parse_network(value):
    if not isinstance(value, str):
        return None
    try:
        if "/" not in value:
            return None
        x = ipaddress.ip_network(value, strict=False)
        return x if x.version == 4 else None
    except ValueError:
        return None


def overlaps_address_routes(addr, routes):
    if not isinstance(addr, list) or not isinstance(routes, list):
        return None
    for interface in addr:
        if not isinstance(interface, dict):
            return None
        rows = interface.get("addr_info")
        if not isinstance(rows, list):
            return None
        for item in rows:
            if item.get("family") != "inet":
                continue
            ip = item.get("local")
            prefix = item.get("prefixlen")
            if not isinstance(ip, str) or not isinstance(prefix, int):
                return None
            network = parse_network(f"{ip}/{prefix}")
            if network is None:
                return None
            if network.overlaps(CANDIDATE):
                return True
    for row in routes:
        if not isinstance(row, dict):
            return None
        dst = row.get("dst")
        if dst is None:
            return None
        if dst == "default":
            continue
        network = parse_network(dst)
        if network and network.overlaps(CANDIDATE):
            return True
    return False


def guest_configs():
    lines = run(["pct", "list"])
    if lines is None:
        return None
    guests = []
    for i, row in enumerate(lines.splitlines()):
        if i == 0:
            continue
        columns = row.split()
        if len(columns) < 2 or not columns[0].isdigit():
            return None
        guests.append((columns[0], columns[1]))
    if len(guests) > GUEST_MAX:
        return None
    return guests


def static_lxc_overlap(vmid):
    raw = run(["pct", "config", vmid], max_output=45000)
    if raw is None:
        return None
    for line in raw.splitlines():
        if not re.match(r"^net[0-9]+:\s", line):
            continue
        m = re.search(r"(?:^|,)ip=([^,]+)", line)
        if m and m.group(1).lower() not in ("dhcp", "manual"):
            n = parse_network(m.group(1))
            if n is None:
                return None
            if n.overlaps(CANDIDATE):
                return True
    return False


def running_lxc_overlap(vmid):
    prefix = ["pct", "exec", vmid, "--", "ip", "-j", "-4"]
    return overlaps_address_routes(
        obj(prefix + ["address", "show"]),
        obj(prefix + ["route", "show", "table", "all"])
    )


def lxc_inventory():
    guests = guest_configs()
    if guests is None:
        return {"state": "UNVERIFIED", "total": "UNVERIFIED",
                "running": "UNVERIFIED", "stopped": "UNVERIFIED"}
    signals = []
    running = 0
    stopped = 0
    for vmid, state in guests:
        signals.append(static_lxc_overlap(vmid))
        if state == "running":
            running += 1
            signals.append(running_lxc_overlap(vmid))
        elif state == "stopped":
            stopped += 1
        else:
            signals.append(None)
    return {
        "state": "OVERLAP_FOUND" if True in signals else
                 ("UNVERIFIED" if None in signals else "NO_OVERLAP_IN_SCANNED_GUESTS"),
        "total": len(guests), "running": running, "stopped": stopped
    }


def named_podman_networks(vmid):
    data = obj(["pct", "exec", vmid, "--",
                "podman", "network", "ls", "--format", "json"])
    if not isinstance(data, list) or len(data) > NETWORK_MAX:
        return None
    names = []
    for row in data:
        if not isinstance(row, dict):
            return None
        name = row.get("name", row.get("Name"))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
            return None
        names.append(name)
    return names


def inspect_podman(vmid):
    names = named_podman_networks(vmid)
    if names is None:
        return "UNVERIFIED"
    found = []
    for name in names:
        data = obj(["pct", "exec", vmid, "--",
                    "podman", "network", "inspect", name])
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            return "UNVERIFIED"
        subnets = data[0].get("subnets", data[0].get("Subnets", []))
        if not isinstance(subnets, list):
            return "UNVERIFIED"
        for sub in subnets:
            if not isinstance(sub, dict):
                return "UNVERIFIED"
            value = sub.get("subnet", sub.get("Subnet"))
            cidr = parse_network(value)
            if cidr is None:
                return "UNVERIFIED"
            found.append(cidr.overlaps(CANDIDATE))
    return "OVERLAP_FOUND" if any(found) else "NO_OVERLAP_IN_SCANNED_NETWORKS"


def inspect_docker_host():
    if shutil.which("docker") is None:
        return "NOT_INSTALLED"
    raw = run(["docker", "network", "ls", "--format", "{{.ID}}"])
    if raw is None:
        return "UNVERIFIED"
    ids = raw.splitlines()
    if len(ids) > NETWORK_MAX or any(not re.fullmatch(r"[0-9a-f]{12,64}", s) for s in ids):
        return "UNVERIFIED"
    found = []
    for id_ in ids:
        data = obj(["docker", "network", "inspect", "-f",
                    "{{json .IPAM.Config}}", id_])
        if not isinstance(data, list):
            return "UNVERIFIED"
        for cfg in data:
            if not isinstance(cfg, dict):
                return "UNVERIFIED"
            value = cfg.get("Subnet")
            if value:
                cidr = parse_network(value)
                if cidr is None:
                    return "UNVERIFIED"
                found.append(cidr.overlaps(CANDIDATE))
    return "OVERLAP_FOUND" if any(found) else "NO_OVERLAP_IN_SCANNED_NETWORKS"


def emit(**values):
    print(FRAME + json.dumps(dict(
        AUDIT="READ_ONLY", CHANGED=False, BRIDGE_CANDIDATE="vmbr90",
        SUBNET_CANDIDATE="172.30.110.0/28",
        UNIFI_AND_VPN_INVENTORY="NOT_INSPECTED",
        QEMU_GUEST_OS_ROUTES="NOT_INSPECTED",
        FULL_NETWORK_CLEARANCE="NOT_PROVEN",
        APPLY_AUTHORIZED=False, NETWORK_CHANGES="NONE",
        PAPERLESS_CHANGED="NO", OLLAMA_CHANGED="NO", **values
    ), sort_keys=True), flush=True)


def main():
    known = {}
    for vmid, hostname in (("110", "bergen-ai"), ("126", "bergen-paperless")):
        cfg = run(["pct", "config", vmid], max_output=35000)
        state = run(["pct", "status", vmid], max_output=200)
        if not cfg or f"hostname: {hostname}" not in cfg.splitlines() or not state or state.strip() != "status: running":
            emit(STATUS="KNOWN_GUEST_IDENTITY_UNVERIFIED", ALL_LXC="UNVERIFIED",
                 LXC_TOTAL="UNVERIFIED", LXC_RUNNING="UNVERIFIED",
                 LXC_STOPPED="UNVERIFIED", PAPERLESS_PODMAN="UNVERIFIED",
                 AI_PODMAN="UNVERIFIED", PVE_HOST_DOCKER="UNVERIFIED")
            return
    lxc = lxc_inventory()
    p126 = inspect_podman("126")
    p110 = inspect_podman("110")
    docker = inspect_docker_host()
    statuses = [lxc["state"], p126, p110, docker]
    if "OVERLAP_FOUND" in statuses:
        result = "OVERLAP_FOUND"
    elif "UNVERIFIED" in statuses:
        result = "SCOPED_AUDIT_INCOMPLETE"
    else:
        result = "NO_OVERLAP_IN_SCANNED_DOMAINS"
    emit(STATUS=result, ALL_LXC=lxc["state"],
         LXC_TOTAL=lxc["total"], LXC_RUNNING=lxc["running"],
         LXC_STOPPED=lxc["stopped"], PAPERLESS_PODMAN=p126,
         AI_PODMAN=p110, PVE_HOST_DOCKER=docker,
         NEXT_ACTION="REVIEW_UNIFI_VPN_QEMU_IPAM_AND_BACKUPS_BEFORE_APPLY")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED", ALL_LXC="UNVERIFIED",
             LXC_TOTAL="UNVERIFIED", LXC_RUNNING="UNVERIFIED",
             LXC_STOPPED="UNVERIFIED", PAPERLESS_PODMAN="UNVERIFIED",
             AI_PODMAN="UNVERIFIED", PVE_HOST_DOCKER="UNVERIFIED")
