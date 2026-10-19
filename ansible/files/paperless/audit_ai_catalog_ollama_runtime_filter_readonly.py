#!/usr/bin/env python3
"""Sanitized read-only runtime rule inventory for Bergen-AI LXC110.

This is NOT an exposure clearance. Reports bounded aggregates from nft,
iptables and a verified LXC110's own port-11434 IPv4/IPv6 listener state.
No raw rules, addresses, interfaces, document data or credentials leave host.
No network requests, configuration writes, firewall changes or restarts.
"""
import json
import re
import subprocess

FRAME="BERGEN_PAPERLESS_OLLAMA_RUNTIME_FILTER_V1:"
BOUNDED=3_000_000

GUEST=r'''
import json,subprocess
def checked(argv):
    try:
        p=subprocess.run(argv,capture_output=True,check=False,timeout=6)
        return p.stdout.decode("utf-8","replace") if p.returncode==0 and len(p.stdout)<=24000 else None
    except (OSError,subprocess.TimeoutExpired):
        return None
def listener(result):
    if result is None:
        return "UNVERIFIED"
    values=[]
    for ln in result.splitlines():
        cols=ln.split()
        if len(cols)<4:
            return "UNVERIFIED"
        local=cols[3]
        if local.rsplit(":",1)[-1]!="11434":
            continue
        values.append(local)
    if not values: return "NONE"
    if any(x.startswith(("[::]:",":::","*:")) for x in values):
        return "WILDCARD"
    return "BOUND_SPECIFIC"
ipv4=checked(["ss","-H","-ltn4"])
ipv6=checked(["ss","-H","-ltn6"])
ip6=checked(["ip","-j","-6","addr","show"])
if ip6 is None:
    globalscope="UNVERIFIED"
else:
    try:
        obj=json.loads(ip6)
        globalscope="PRESENT" if any(
            entry.get("scope")=="global" and entry.get("family")=="inet6"
            for iface in obj for entry in iface.get("addr_info",[])
        ) else "ABSENT"
    except (TypeError,ValueError,AttributeError):
        globalscope="UNVERIFIED"
print("BERGEN_PAPERLESS_OLLAMA_GUEST_FILTER_V1:"+json.dumps({
    "ipv4_listener":listener(ipv4),
    "ipv6_listener":listener(ipv6),
    "ipv6_global_or_ula":globalscope
},sort_keys=True))
'''


def run(args,timeout=15,bound=BOUNDED):
    try:
        p=subprocess.run(args,capture_output=True,check=False,timeout=timeout)
        if p.returncode!=0 or len(p.stdout)>bound:
            return None
        return p.stdout.decode("utf-8","replace")
    except (OSError,subprocess.TimeoutExpired):
        return None


def framed(text,prefix):
    if not isinstance(text,str):
        return None
    frames=[line[len(prefix):] for line in text.splitlines()
            if line.startswith(prefix)]
    if len(frames)!=1 or len(frames[0])>1600:
        return None
    try:
        return json.loads(frames[0])
    except (ValueError,TypeError):
        return None


def nft_inspect():
    raw=run(["nft","-j","list","ruleset"])
    if raw is None:
        return ("UNAVAILABLE", "UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
    try:
        document=json.loads(raw)
        elements=document["nftables"]
        if not isinstance(elements,list) or len(elements)>40000:
            raise ValueError("INVALID_NFT_JSON")
        chaincount=0
        basechaincount=0
        device_mentions=0
        port_mentions=0
        for item in elements:
            if not isinstance(item,dict):
                continue
            if "chain" in item and isinstance(item["chain"],dict):
                chain=item["chain"]
                if chain.get("family") in ("bridge","inet","ip","ip6","netdev"):
                    chaincount+=1
                    if chain.get("hook") in ("input","forward","prerouting","ingress"):
                        basechaincount+=1
            if "rule" in item and isinstance(item["rule"],dict):
                rule=item["rule"]
                expr=rule.get("expr")
                if isinstance(expr,list):
                    serial=json.dumps(expr,separators=(",",":"))
                    if re.search(r'\b11434\b',serial):
                        port_mentions+=1
                    if re.search(r'\bveth110i[0-9]+\b',serial):
                        device_mentions+=1
        return ("LOADED", str(basechaincount), str(port_mentions),
                "PRESENT" if device_mentions else "NOT_OBSERVED")
    except (ValueError,TypeError,KeyError):
        return ("UNVERIFIED","UNVERIFIED","UNVERIFIED","UNVERIFIED")


def iptables_inspect(binary):
    raw=run([binary],bound=500000)
    if raw is None:
        return ("UNAVAILABLE","UNVERIFIED","UNVERIFIED")
    rules=[line for line in raw.splitlines() if line.startswith("-A ")]
    return ("AVAILABLE",str(len(rules)),
            "PRESENT" if any(re.search(r'\bveth110i[0-9]+\b',ln) for ln in rules)
            else "NOT_OBSERVED")


def emit(**values):
    print(FRAME+json.dumps(dict(AUDIT="READ_ONLY",CHANGED=False,
                               EXPOSURE_GATE="REVIEW_REQUIRED",
                               UNIFI_POLICY="NOT_INSPECTED",**values),
                           sort_keys=True),flush=True)


def main():
    cfg=run(["pct","config","110"],bound=20000)
    status=run(["pct","status","110"],bound=200)
    if (not cfg or "hostname: bergen-ai" not in cfg.splitlines()
        or "unprivileged: 1" not in cfg.splitlines()
        or status is None or status.strip()!="status: running"):
        emit(STATUS="CT110_UNVERIFIED",
             NFT_STATUS="UNVERIFIED",
             NFT_BASE_CHAINS="UNVERIFIED",
             NFT_PORT_11434_RULE_HINTS="UNVERIFIED",
             NFT_CT110_INTERFACE_MENTION="UNVERIFIED",
             IPT4_STATUS="UNVERIFIED",IPT6_STATUS="UNVERIFIED",
             IPT4_CT110_INTERFACE_MENTION="UNVERIFIED",
             IPT6_CT110_INTERFACE_MENTION="UNVERIFIED",
             IPV4_LISTENER="UNVERIFIED",IPV6_LISTENER="UNVERIFIED",
             IPV6_NON_LINK_LOCAL="UNVERIFIED")
        return

    raw=run(["pct","exec","110","--","python3","-c",GUEST],bound=3000,timeout=22)
    state=framed(raw,"BERGEN_PAPERLESS_OLLAMA_GUEST_FILTER_V1:")
    if not isinstance(state,dict) or set(state)!={
            "ipv4_listener","ipv6_listener","ipv6_global_or_ula"}:
        state={}
    listeners={
        "IPV4_LISTENER":state.get("ipv4_listener","UNVERIFIED"),
        "IPV6_LISTENER":state.get("ipv6_listener","UNVERIFIED"),
        "IPV6_NON_LINK_LOCAL":state.get("ipv6_global_or_ula","UNVERIFIED")
    }
    allowed_listener={"UNVERIFIED","NONE","WILDCARD","BOUND_SPECIFIC"}
    if listeners["IPV4_LISTENER"] not in allowed_listener:
        listeners["IPV4_LISTENER"]="UNVERIFIED"
    if listeners["IPV6_LISTENER"] not in allowed_listener:
        listeners["IPV6_LISTENER"]="UNVERIFIED"
    if listeners["IPV6_NON_LINK_LOCAL"] not in {"UNVERIFIED","PRESENT","ABSENT"}:
        listeners["IPV6_NON_LINK_LOCAL"]="UNVERIFIED"

    nftstatus,basechains,porthints,devhints=nft_inspect()
    ipt4,ipt4count,ipt4dev=iptables_inspect("iptables-save")
    ipt6,ipt6count,ipt6dev=iptables_inspect("ip6tables-save")
    emit(STATUS="RUNTIME_RULE_INVENTORY",
         NFT_STATUS=nftstatus,NFT_BASE_CHAINS=basechains,
         NFT_PORT_11434_RULE_HINTS=porthints,
         NFT_CT110_INTERFACE_MENTION=devhints,
         IPT4_STATUS=ipt4,IPT6_STATUS=ipt6,
         IPT4_RULE_COUNT=ipt4count,IPT6_RULE_COUNT=ipt6count,
         IPT4_CT110_INTERFACE_MENTION=ipt4dev,
         IPT6_CT110_INTERFACE_MENTION=ipt6dev,
         EFFECTIVE_TCP_11434_DENY="NOT_VERIFIED",
         INTRA_VLAN_ISOLATION="NOT_VERIFIED",
         **listeners)


if __name__=="__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED",NFT_STATUS="UNVERIFIED",
             NFT_BASE_CHAINS="UNVERIFIED",
             NFT_PORT_11434_RULE_HINTS="UNVERIFIED",
             NFT_CT110_INTERFACE_MENTION="UNVERIFIED",
             IPT4_STATUS="UNVERIFIED",IPT6_STATUS="UNVERIFIED",
             IPT4_CT110_INTERFACE_MENTION="UNVERIFIED",
             IPT6_CT110_INTERFACE_MENTION="UNVERIFIED",
             IPV4_LISTENER="UNVERIFIED",IPV6_LISTENER="UNVERIFIED",
             IPV6_NON_LINK_LOCAL="UNVERIFIED")
