#!/usr/bin/env python3
"""Read-only WireGuard peer AllowedIPs comparison for candidate AI /28.

Checks LIVE WireGuard peers only on verified venombox host and LXC110/126/120.
Never reads private keys or config files. Raw peer public keys, interfaces and
network addresses are never printed in summaries. Never changes interfaces,
WireGuard settings, service state, network routes, or application data.
A nonoverlap result does NOT clear remote VPNs, inactive WG interfaces or IPAM.
"""
import ipaddress
import json
import shutil
import subprocess

FRAME = "BERGEN_AI_BRIDGE_WG_PREFLIGHT_V1:"
GUEST_FRAME = "BERGEN_AI_WG_GUEST_V1:"
CANDIDATE = ipaddress.ip_network("172.30.110.0/28")
GUESTS = (("110", "bergen-ai"), ("126", "bergen-paperless"), ("120", "bergen-syslog"))

GUEST_SOURCE = r'''
import ipaddress,json,shutil,subprocess
candidate=ipaddress.ip_network("172.30.110.0/28")
status="UNVERIFIED"
try:
    if shutil.which("wg") is None:
        status="NOT_INSTALLED"
    else:
        p=subprocess.run(["wg","show","all","allowed-ips"],
            capture_output=True,timeout=7,check=False)
        if p.returncode==0 and len(p.stdout)<=200000:
            data=p.stdout.decode("utf-8","replace")
            if not data.strip():
                status="NO_ACTIVE_PEER_PREFIXES"
            else:
                found=[]
                for line in data.splitlines():
                    columns=line.split()
                    if len(columns)!=3:
                        raise ValueError("UNRECOGNIZED_WG_OUTPUT")
                    for cidr in columns[2].split(","):
                        network=ipaddress.ip_network(cidr,strict=False)
                        if network.version==4:
                            found.append(network.overlaps(candidate))
                status="OVERLAP_FOUND" if any(found) else "NO_OVERLAP_IN_ACTIVE_PEERS"
except Exception:
    status="UNVERIFIED"
print("BERGEN_AI_WG_GUEST_V1:"+json.dumps({"state":status}))
'''


def checked(argv, timeout=14, limit=2600):
    try:
        p = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
        if p.returncode != 0 or len(p.stdout) > limit:
            return None
        return p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def parse_frame(raw):
    if not isinstance(raw, str):
        return "UNVERIFIED"
    frames = [x[len(GUEST_FRAME):] for x in raw.splitlines()
              if x.startswith(GUEST_FRAME)]
    if len(frames) != 1 or len(frames[0]) > 260:
        return "UNVERIFIED"
    try:
        value = json.loads(frames[0])
        if (not isinstance(value, dict) or set(value) != {"state"} or
            value["state"] not in {
                "NOT_INSTALLED", "NO_ACTIVE_PEER_PREFIXES",
                "NO_OVERLAP_IN_ACTIVE_PEERS", "OVERLAP_FOUND", "UNVERIFIED"
            }):
            return "UNVERIFIED"
        return value["state"]
    except (ValueError, TypeError):
        return "UNVERIFIED"


def guest_status(vmid, hostname):
    config = checked(["pct", "config", vmid], limit=30000)
    state = checked(["pct", "status", vmid], limit=100)
    if (not config or f"hostname: {hostname}" not in config.splitlines()
        or "unprivileged: 1" not in config.splitlines()
        or not state or state.strip() != "status: running"):
        return "UNVERIFIED"
    return parse_frame(checked(
        ["pct", "exec", vmid, "--", "python3", "-c", GUEST_SOURCE],
        timeout=15, limit=700))


def host_status():
    return parse_frame(checked(["python3", "-c", GUEST_SOURCE],
                               timeout=12, limit=700))


def summarize(states):
    if "OVERLAP_FOUND" in states:
        return "OVERLAP_FOUND"
    if "UNVERIFIED" in states:
        return "INCOMPLETE"
    return "NO_OVERLAP_IN_INSPECTED_LIVE_WG_PEERS"


def emit(**values):
    print(FRAME + json.dumps(dict(
        AUDIT="READ_ONLY", CHANGED=False, BRIDGE_CANDIDATE="vmbr90",
        SUBNET_CANDIDATE="172.30.110.0/28",
        INACTIVE_WG_TUNNELS="NOT_INSPECTED",
        REMOTE_WG_PEERS_AND_SITES="NOT_INSPECTED",
        OTHER_VPN_TECHNOLOGIES="NOT_INSPECTED",
        FULL_NETWORK_CLEARANCE="NOT_PROVEN",
        APPLY_AUTHORIZED=False, NETWORK_CHANGES="NONE",
        OLLAMA_CHANGED="NO", PAPERLESS_CHANGED="NO", **values),
        sort_keys=True), flush=True)


def main():
    states = [host_status()] + [guest_status(vmid, hostname)
                                for vmid, hostname in GUESTS]
    emit(STATUS=summarize(states), WG_HOST=states[0],
         WG_LXC110=states[1], WG_LXC126=states[2], WG_LXC120=states[3],
         NEXT_ACTION="REVIEW_REMOTE_VPN_IPAM_BACKUPS_AND_ROLLBACK_BEFORE_ANY_APPLY")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit(STATUS="INCOMPLETE", WG_HOST="UNVERIFIED",
             WG_LXC110="UNVERIFIED", WG_LXC126="UNVERIFIED",
             WG_LXC120="UNVERIFIED")
