#!/usr/bin/env python3
"""One owner-approved read-only TCP/11434 exposure test from bp-controller.

No HTTP requests or model inference. Discover LXC110 private addresses from
verified venombox only; verify bp-controller's own source address before any
connect. The secret-less intermediate discovery frame is held behind Ansible
no_log. The final report never displays addresses or raw network errors.
"""
import errno
import ipaddress
import json
import socket
import subprocess
import sys

FRAME="BERGEN_AI_OLLAMA_NEGATIVE_PROBE_V1:"
IP_DISCOVERY=r'''
import ipaddress,json,subprocess
result={"ipv4":[],"ipv6":[]}
try:
    for fam,name in ((4,"ipv4"),(6,"ipv6")):
        r=subprocess.run(["ip","-j",f"-{fam}","addr","show"],
                         capture_output=True,timeout=6,check=False)
        if r.returncode or len(r.stdout)>64000:
            raise ValueError("FAILED_NETWORK_DISCOVERY")
        interfaces=json.loads(r.stdout)
        for iface in interfaces:
            if iface.get("ifname")=="lo":
                continue
            for item in iface.get("addr_info",[]):
                if item.get("family")!=("inet" if fam==4 else "inet6"):
                    continue
                addr=ipaddress.ip_address(item.get("local",""))
                if (addr.version==fam and not addr.is_loopback and
                    not addr.is_link_local and not addr.is_multicast and
                    not addr.is_unspecified and
                    (addr.is_private if fam==4 else
                    (addr.is_global or addr in ipaddress.ip_network("fc00::/7")))):
                    result[name].append(str(addr))
    result={k:sorted(set(v)) for k,v in result.items()}
    if len(result["ipv4"])!=1 or len(result["ipv6"])>1:
        raise ValueError("AMBIGUOUS_TARGET")
    result["status"]="BOUNDED_TARGET"
except Exception:
    result={"status":"UNVERIFIED","ipv4":[],"ipv6":[]}
print("BERGEN_AI_OLLAMA_LXC110_ADDRESS_V1:"+json.dumps(result,sort_keys=True))
'''


def run(argv,timeout=15,cap=12000):
    try:
        result=subprocess.run(argv,capture_output=True,check=False,timeout=timeout)
        if result.returncode!=0 or len(result.stdout)>cap:
            return None
        return result.stdout.decode("utf-8","replace")
    except (OSError,subprocess.TimeoutExpired):
        return None


def frame(value,prefix):
    if not isinstance(value,str):
        return None
    lines=[row[len(prefix):] for row in value.splitlines()
           if row.startswith(prefix)]
    if len(lines)!=1 or len(lines[0])>1200:
        return None
    try:
        return json.loads(lines[0])
    except (ValueError,TypeError):
        return None


def emit(**values):
    print(FRAME+json.dumps(dict(AUDIT="READ_ONLY",CHANGED=False,**values),
                           sort_keys=True),flush=True)


def discover():
    cfg=run(["pct","config","110"])
    state=run(["pct","status","110"],cap=120)
    if (not cfg or "hostname: bergen-ai" not in cfg.splitlines()
        or "unprivileged: 1" not in cfg.splitlines()
        or not state or state.strip()!="status: running"):
        emit(STATUS="TARGET_IDENTITY_UNVERIFIED")
        return
    output=frame(run(["pct","exec","110","--","python3","-c",IP_DISCOVERY],
                     timeout=20,cap=1800),
                 "BERGEN_AI_OLLAMA_LXC110_ADDRESS_V1:")
    if (not isinstance(output,dict) or output.get("status")!="BOUNDED_TARGET"
        or set(output)!={"status","ipv4","ipv6"}
        or not isinstance(output["ipv4"],list)
        or not isinstance(output["ipv6"],list)
        or len(output["ipv4"])!=1 or len(output["ipv6"])>1):
        emit(STATUS="TARGET_ADDRESS_UNVERIFIED")
        return
    emit(STATUS="TARGET_DISCOVERED",IPV4=output["ipv4"][0],
         IPV6=output["ipv6"][0] if output["ipv6"] else "")


def local_ipv4_contains(expected):
    if not expected:
        return False
    try:
        address=ipaddress.ip_address(expected)
        if address.version!=4 or not address.is_private:
            return False
        raw=run(["ip","-j","-4","addr","show"],timeout=8,cap=64000)
        if raw is None:
            return False
        return any(
            item.get("local")==expected
            for iface in json.loads(raw)
            for item in iface.get("addr_info",[])
        )
    except (ValueError,TypeError,AttributeError):
        return False


def tcp_11434(address,family):
    if not address:
        return "NO_TARGET_ADDRESS"
    try:
        dest=ipaddress.ip_address(address)
        if (dest.version != (4 if family==socket.AF_INET else 6)
            or dest.is_loopback or dest.is_link_local
            or dest.is_unspecified or dest.is_multicast
            or (dest.version==4 and not dest.is_private)
            or (dest.version==6 and
                not (dest.is_global or dest in ipaddress.ip_network("fc00::/7")))):
            return "TARGET_UNVERIFIED"
        sock=socket.socket(family,socket.SOCK_STREAM)
        try:
            sock.settimeout(3.0)
            err=sock.connect_ex((str(dest),11434))
            if err==0:
                return "REACHABLE"
            if err==errno.ECONNREFUSED:
                return "REFUSED"
            if err in (errno.EHOSTUNREACH,errno.ENETUNREACH,
                       errno.EADDRNOTAVAIL):
                return "NO_ROUTE"
            if err==errno.ETIMEDOUT:
                return "TIMEOUT"
            return "UNVERIFIED_NETWORK_ERROR"
        except socket.timeout:
            return "TIMEOUT"
        finally:
            sock.close()
    except (OSError,ValueError,TypeError):
        return "UNVERIFIED_NETWORK_ERROR"


def probe(argv):
    if len(argv)!=3:
        emit(STATUS="SOURCE_OR_TARGET_UNVERIFIED")
        return
    expected_source,ipv4,ipv6=argv
    if not local_ipv4_contains(expected_source):
        emit(STATUS="SOURCE_IDENTITY_UNVERIFIED")
        return
    a=tcp_11434(ipv4,socket.AF_INET)
    b=tcp_11434(ipv6,socket.AF_INET6)
    allowed={"REACHABLE","REFUSED","NO_ROUTE","TIMEOUT",
             "NO_TARGET_ADDRESS","TARGET_UNVERIFIED","UNVERIFIED_NETWORK_ERROR"}
    if a not in allowed or b not in allowed:
        emit(STATUS="SOURCE_OR_TARGET_UNVERIFIED")
        return
    emit(STATUS="PROBE_COMPLETED",
         SOURCE="BP_CONTROLLER_ONLY",
         IPV4_TCP_11434=a,IPV6_TCP_11434=b,
         EXTERNAL_CLIENT_ACCESS="REACHABLE" if
             "REACHABLE" in (a,b) else "NOT_PROVEN_OPEN",
         SECURITY_GATE="REVIEW_REQUIRED",
         NOTES="CONNECT_ONLY_NO_HTTP_NO_LLM")


if __name__=="__main__":
    try:
        if len(sys.argv)>=2 and sys.argv[1]=="discover" and len(sys.argv)==2:
            discover()
        elif len(sys.argv)>=2 and sys.argv[1]=="probe":
            probe(sys.argv[2:])
        else:
            emit(STATUS="INVALID_MODE")
    except Exception:
        emit(STATUS="UNVERIFIED")
