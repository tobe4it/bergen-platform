#!/usr/bin/env python3
"""Read-only LXC110/LXC126 PVE network topology and Podman route classification.

No IPs, MACs, bridge names, VLAN IDs or application data emitted. No HTTP,
inference, packet injection, restart, config change, iptables modification.
UDP connect() reads a local routing decision but sends NO datagrams; it
does NOT reveal actual source address after Podman/host NAT.
"""
import ipaddress
import json
import re
import socket
import subprocess

FRAME="BERGEN_PAPERLESS_OLLAMA_TOPOLOGY_V1:"

TARGET_GUEST=r'''
import ipaddress,json,subprocess
try:
    p=subprocess.run(["ip","-j","-4","addr","show"],capture_output=True,timeout=5)
    if p.returncode or len(p.stdout)>60000:
        raise ValueError("IP_READ_FAILED")
    choices=set()
    for iface in json.loads(p.stdout):
        if iface.get("ifname")=="lo":
            continue
        for row in iface.get("addr_info",[]):
            if row.get("family")=="inet":
                v=ipaddress.ip_address(row.get("local",""))
                if v.version==4 and v.is_private and not v.is_link_local and not v.is_loopback:
                    choices.add(str(v))
    value=next(iter(choices)) if len(choices)==1 else ""
    print("BERGEN_TOPOLOGY_TARGET_GUEST_V1:"+json.dumps({"ip":value,"unique":len(choices)==1}))
except Exception:
    print("BERGEN_TOPOLOGY_TARGET_GUEST_V1:"+json.dumps({"ip":"","unique":False}))
'''

SOURCE_ROUTE=r'''
import json,socket,sys
status="UNVERIFIED"
try:
    if len(sys.argv)==2:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.connect((sys.argv[1],11434))
            source=s.getsockname()[0]
        status=source if source and source!="0.0.0.0" else "UNVERIFIED"
except Exception:
    pass
print("BERGEN_TOPOLOGY_LOCAL_ROUTE_V1:"+json.dumps({"source":status}))
'''


def checked(args,timeout=15,limit=16000):
    try:
        result=subprocess.run(args,capture_output=True,timeout=timeout,check=False)
        if result.returncode != 0 or len(result.stdout)>limit:
            return None
        return result.stdout.decode("utf-8","replace")
    except (OSError,subprocess.TimeoutExpired):
        return None


def frame(s,prefix,limit=900):
    if not isinstance(s,str):
        return None
    rows=[r[len(prefix):] for r in s.splitlines() if r.startswith(prefix)]
    if len(rows)!=1 or len(rows[0])>limit:
        return None
    try:
        obj=json.loads(rows[0])
        return obj if isinstance(obj,dict) else None
    except (ValueError,TypeError):
        return None


def net_config(s):
    n={}
    for line in s.splitlines():
        m=re.fullmatch(r"net([0-9]+):\s*(.+)",line)
        if m:
            options={}
            for segment in m.group(2).split(","):
                if "=" in segment:
                    k,v=segment.split("=",1)
                    options[k.strip()]=v.strip()
            n[m.group(1)]=options
    return n


def classification(n1,n2):
    if len(n1)!=1 or len(n2)!=1:
        return {"NETS_LXC110":"ONE" if len(n1)==1 else "NOT_ONE",
                "NETS_LXC126":"ONE" if len(n2)==1 else "NOT_ONE",
                "SAME_PVE_BRIDGE":"NOT_VERIFIED",
                "SAME_CONFIGURED_VLAN":"NOT_VERIFIED",
                "PVE_BOTH_NIC_FIREWALL_ENABLED":"NOT_VERIFIED"}
    a=next(iter(n1.values()))
    b=next(iter(n2.values()))
    bridge=bool(a.get("bridge")) and bool(b.get("bridge"))
    tag=(a.get("tag","UNTAGGED") == b.get("tag","UNTAGGED"))
    both_fw=a.get("firewall")=="1" and b.get("firewall")=="1"
    return {"NETS_LXC110":"ONE","NETS_LXC126":"ONE",
            "SAME_PVE_BRIDGE":"YES" if bridge and a["bridge"]==b["bridge"] else
                ("NO" if bridge else "NOT_VERIFIED"),
            "SAME_CONFIGURED_VLAN":"YES" if tag else "NO",
            "PVE_BOTH_NIC_FIREWALL_ENABLED":"YES" if both_fw else "NO"}


def emit(**values):
    print(FRAME+json.dumps(dict(AUDIT="READ_ONLY",CHANGED=False,
        ACTUAL_LXC110_INBOUND_SOURCE="NOT_DEMONSTRATED",
        IPV6_FIREWALL_POLICY="NOT_VERIFIED",
        EXPOSURE_GATE="REVIEW_REQUIRED",**values),
        sort_keys=True),flush=True)


def valid_address(s):
    try:
        addr=ipaddress.ip_address(s)
        return addr.version==4 and addr.is_private and not addr.is_loopback and not addr.is_link_local
    except (ValueError,TypeError):
        return False


def main():
    ct={}
    for id_,name in (("110","bergen-ai"),("126","bergen-paperless")):
        raw=checked(["pct","config",id_])
        status=checked(["pct","status",id_],limit=100)
        if (not raw or f"hostname: {name}" not in raw.splitlines()
            or "unprivileged: 1" not in raw.splitlines()
            or not status or status.strip()!="status: running"):
            emit(STATUS="LXC_IDENTITIES_NOT_VERIFIED",
                 NETS_LXC110="UNVERIFIED",NETS_LXC126="UNVERIFIED",
                 SAME_PVE_BRIDGE="NOT_VERIFIED",
                 SAME_CONFIGURED_VLAN="NOT_VERIFIED",
                 PVE_BOTH_NIC_FIREWALL_ENABLED="NOT_VERIFIED",
                 PAPERLESS_ROUTE_SOURCE="NOT_VERIFIED")
            return
        ct[id_]=net_config(raw)
    topo=classification(ct["110"],ct["126"])
    target=frame(checked(["pct","exec","110","--","python3","-c",TARGET_GUEST],
                         timeout=18,limit=1500),
                 "BERGEN_TOPOLOGY_TARGET_GUEST_V1:")
    if not target or target.get("unique") is not True or not valid_address(target.get("ip")):
        emit(STATUS="TARGET_ROUTE_UNVERIFIED",PAPERLESS_ROUTE_SOURCE="NOT_VERIFIED",**topo)
        return
    ip=target["ip"]
    guest=frame(checked(["pct","exec","126","--","python3","-c",SOURCE_ROUTE,ip],
                        timeout=18,limit=1500),
                "BERGEN_TOPOLOGY_LOCAL_ROUTE_V1:")
    podman=frame(checked(["pct","exec","126","--","podman","exec","bergen-paperless",
                          "python","-c",SOURCE_ROUTE,ip],timeout=18,limit=1500),
                 "BERGEN_TOPOLOGY_LOCAL_ROUTE_V1:")
    a=guest.get("source") if isinstance(guest,dict) else None
    b=podman.get("source") if isinstance(podman,dict) else None
    if valid_address(a) and valid_address(b):
        route="MATCHES_LXC126_ROUTE" if a==b else "DIFFERENT_FROM_LXC126_ROUTE"
    else:
        route="UNVERIFIED"
    emit(STATUS="TOPOLOGY_CLASSIFIED",PAPERLESS_ROUTE_SOURCE=route,
         SOURCE_NAT_EFFECTIVE="NOT_PROVEN",
         INTRA_VLAN_POLICY="NOT_VERIFIED",**topo)


if __name__=="__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED",NETS_LXC110="UNVERIFIED",
             NETS_LXC126="UNVERIFIED",SAME_PVE_BRIDGE="NOT_VERIFIED",
             SAME_CONFIGURED_VLAN="NOT_VERIFIED",
             PVE_BOTH_NIC_FIREWALL_ENABLED="NOT_VERIFIED",
             PAPERLESS_ROUTE_SOURCE="NOT_VERIFIED")
