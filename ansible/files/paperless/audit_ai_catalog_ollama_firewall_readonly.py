#!/usr/bin/env python3
"""Read-only Proxmox firewall *configuration inventory* for Bergen-AI CT110.

No scan, firewall changes, network modifications, restart or document access.
Never output IPs, interfaces, other guests' data, or raw firewall rules.
Configuration is NOT proof of effective packet filtering or UniFi policies.
"""
import json
from pathlib import Path
import re
import subprocess

FRAME="BERGEN_PAPERLESS_OLLAMA_FIREWALL_V1:"

def run(args, timeout=8, bound=24000):
    try:
        p=subprocess.run(args,capture_output=True,check=False,timeout=timeout)
        if p.returncode!=0 or len(p.stdout)>bound:
            return None
        return p.stdout.decode("utf-8","replace")
    except (OSError,subprocess.TimeoutExpired):
        return None

def service(unit):
    try:
        p=subprocess.run(["systemctl","is-active",unit],capture_output=True,
                         check=False,timeout=5)
        value=p.stdout.decode("ascii","replace").strip()
        return value.upper() if value in (
            "active","inactive","failed","activating","deactivating") else "UNVERIFIED"
    except (OSError,subprocess.TimeoutExpired):
        return "UNVERIFIED"

def network_flags(config):
    nets=[value for key,value in re.findall(
        r"(?m)^(net[0-9]+):\s*([^\n]+)$",config)]
    if not nets:
        return "UNKNOWN"
    flags=[]
    for value in nets:
        m=re.search(r"(?:^|,)firewall=([01])(?:,|$)",value)
        flags.append(m.group(1) if m else None)
    if all(x=="1" for x in flags):
        return "ENABLED_ALL_NETS"
    if any(x=="0" for x in flags):
        return "DISABLED_SOME_NETS"
    return "UNSPECIFIED_SOME_NETS"

def config_status(path):
    if path.is_symlink():
        return "SYMLINK_UNREVIEWED"
    try:
        return "PRESENT" if path.is_file() else "ABSENT"
    except OSError:
        return "UNVERIFIED"

def option_enabled(path):
    if path.is_symlink():
        return "UNVERIFIED"
    try:
        if not path.is_file():
            return "NO_CONFIG_FILE"
        raw=path.read_text(encoding="utf-8")
        if len(raw)>100000:
            return "UNVERIFIED"
        sections=re.split(r"(?m)^\[([^\]]+)\]\s*$",raw)
        if len(sections)<3:
            return "NOT_EXPLICIT"
        for j in range(1,len(sections)-1,2):
            if sections[j].strip().upper()=="OPTIONS":
                found=re.findall(r"(?m)^\s*enable:\s*([01])\s*$",
                                 sections[j+1])
                if len(found)==1:
                    return "ENABLED" if found[0]=="1" else "DISABLED"
                return "NOT_EXPLICIT"
        return "NOT_EXPLICIT"
    except (OSError,UnicodeError):
        return "UNVERIFIED"

def emit(**kwargs):
    print(FRAME+json.dumps(dict(AUDIT="READ_ONLY",CHANGED=False,**kwargs),
                          sort_keys=True),flush=True)

def main():
    config=run(["pct","config","110"])
    if (not config or "hostname: bergen-ai" not in config.splitlines()
        or "unprivileged: 1" not in config.splitlines()
        or run(["pct","status","110"]).strip()!="status: running"):
        emit(STATUS="CT110_IDENTITY_OR_RUNTIME_UNVERIFIED",
             NETWORK_OPTION="UNVERIFIED",
             CT_RULE_FILE="UNVERIFIED",CLUSTER_ENABLE="UNVERIFIED",
             NODE_ENABLE="UNVERIFIED",
             PVE_FIREWALL_SERVICE="UNVERIFIED",
             NFT_FIREWALL_SERVICE="UNVERIFIED",
             PACKET_ENFORCEMENT="UNVERIFIED",
             UNIFI_POLICY="NOT_INSPECTED",
             EXPOSURE_GATE="REVIEW_REQUIRED")
        return
    node=run(["hostname","-s"])
    if not node or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}",node.strip()):
        node=""
    nodeconfig=(Path("/etc/pve/nodes")/node.strip()/"host.fw") if node else None
    emit(
        STATUS="CONFIGURATION_INVENTORY",
        NETWORK_OPTION=network_flags(config),
        CT_RULE_FILE=config_status(Path("/etc/pve/firewall/110.fw")),
        CLUSTER_ENABLE=option_enabled(Path("/etc/pve/firewall/cluster.fw")),
        NODE_ENABLE=option_enabled(nodeconfig) if nodeconfig else "UNVERIFIED",
        PVE_FIREWALL_SERVICE=service("pve-firewall"),
        NFT_FIREWALL_SERVICE=service("proxmox-firewall"),
        PACKET_ENFORCEMENT="NOT_DEMONSTRATED",
        UNIFI_POLICY="NOT_INSPECTED",
        INTRA_VLAN_ISOLATION="NOT_VERIFIED",
        EXPOSURE_GATE="REVIEW_REQUIRED",
    )

if __name__=="__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED",NETWORK_OPTION="UNVERIFIED",
             CT_RULE_FILE="UNVERIFIED",CLUSTER_ENABLE="UNVERIFIED",
             NODE_ENABLE="UNVERIFIED",PVE_FIREWALL_SERVICE="UNVERIFIED",
             NFT_FIREWALL_SERVICE="UNVERIFIED",
             PACKET_ENFORCEMENT="UNVERIFIED",
             UNIFI_POLICY="NOT_INSPECTED",
             EXPOSURE_GATE="REVIEW_REQUIRED")
