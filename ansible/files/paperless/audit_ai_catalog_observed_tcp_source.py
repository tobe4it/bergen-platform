#!/usr/bin/env python3
"""Observe one authorized synthetic *TCP-only* Paperless->Ollama connection.

This is a live, individually approved connectivity audit, NOT a passive audit
or an AI inference. It sends zero HTTP requests, model prompts and payloads.
The host observes exactly one new established socket on LXC110:11434. All
addresses are held locally; user output is only a categorical source match.
Never write firewall, routes, Paperless, LLM state or documents.
"""
import ipaddress
import json
import subprocess
import sys
import time

FRAME="BERGEN_AI_PAPERLESS_SOURCE_OBSERVATION_V1:"
TARGET_GUEST=r'''
import json,ipaddress,subprocess
try:
    p=subprocess.run(["ip","-j","-4","addr","show"],capture_output=True,
                     check=False,timeout=5)
    if p.returncode or len(p.stdout)>40000: raise ValueError("NO_GUEST_IP")
    result=set()
    for iface in json.loads(p.stdout):
        if iface.get("ifname")=="lo": continue
        for item in iface.get("addr_info",[]):
            if item.get("family")!="inet": continue
            addr=ipaddress.ip_address(item.get("local",""))
            if addr.version==4 and addr.is_private and not addr.is_loopback and not addr.is_link_local:
                result.add(str(addr))
    print("BERGEN_AI_SOURCE_ADDRESS_V1:"+json.dumps({
        "status":"SINGLE" if len(result)==1 else "AMBIGUOUS",
        "address":next(iter(result)) if len(result)==1 else ""
    }))
except Exception:
    print("BERGEN_AI_SOURCE_ADDRESS_V1:"+json.dumps({"status":"UNVERIFIED","address":""}))
'''
ROUTE_GUEST=r'''
import json,socket,sys
source=""
try:
    if len(sys.argv)==2:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.connect((sys.argv[1],11434))  # Routing decision only; no UDP datagrams.
            source=s.getsockname()[0]
except Exception: pass
print("BERGEN_AI_SOURCE_ROUTE_V1:"+json.dumps({"source":source}))
'''
CONNECT_GUEST=r'''
import json,socket,sys,time
try:
    if len(sys.argv)!=2: raise ValueError("BAD_ARGUMENTS")
    with socket.create_connection((sys.argv[1],11434),timeout=4) as s:
        # Deliberately send no data. A short idle socket only.
        print("BERGEN_AI_SOURCE_CLIENT_V1:"+json.dumps({"status":"HELD"}),flush=True)
        time.sleep(8)
    print("BERGEN_AI_SOURCE_CLIENT_V1:"+json.dumps({"status":"CLOSED"}),flush=True)
except Exception:
    print("BERGEN_AI_SOURCE_CLIENT_V1:"+json.dumps({"status":"FAILED"}),flush=True)
'''


def run(args,timeout=20,cap=15000):
    try:
        p=subprocess.run(args,capture_output=True,check=False,timeout=timeout)
        if p.returncode or len(p.stdout)>cap: return None
        return p.stdout.decode("utf-8","replace")
    except (OSError,subprocess.TimeoutExpired):
        return None


def frame(raw,prefix,limit=1400):
    if not isinstance(raw,str): return None
    frames=[line[len(prefix):] for line in raw.splitlines()
            if line.startswith(prefix)]
    if len(frames)!=1 or len(frames[0])>limit: return None
    try:
        obj=json.loads(frames[0])
        return obj if isinstance(obj,dict) else None
    except (ValueError,TypeError):
        return None


def address_valid(text):
    try:
        addr=ipaddress.ip_address(text)
        return addr.version==4 and addr.is_private and not addr.is_loopback and not addr.is_link_local and not addr.is_unspecified
    except (ValueError,TypeError):
        return False


def guest_address(id_):
    data=frame(run(["pct","exec",id_,"--","python3","-c",TARGET_GUEST],
                   timeout=18,cap=1800),"BERGEN_AI_SOURCE_ADDRESS_V1:")
    return data["address"] if data and data.get("status")=="SINGLE" and address_valid(data.get("address")) else None


def route(id_,target,podman=False):
    base=["pct","exec",id_,"--"]
    if podman: base+=["podman","exec","bergen-paperless"]
    data=frame(run(base+["python3","-c",ROUTE_GUEST,target],
                   timeout=18,cap=1800),"BERGEN_AI_SOURCE_ROUTE_V1:")
    value=data.get("source") if data else None
    return value if address_valid(value) else None


def peers():
    # Enumerate only established TCP sockets *local* to Ollama's port.
    raw=run(["pct","exec","110","--","ss","-Htn","state","established"],cap=100000)
    if raw is None: return None
    found=[]
    for line in raw.splitlines():
        fields=line.split()
        if len(fields)<5: return None
        local,remote=fields[-2],fields[-1]
        if local.rsplit(":",1)[-1]!="11434": continue
        host=remote.rsplit(":",1)[0].strip("[]")
        try:
            addr=ipaddress.ip_address(host)
            if addr.version==6 and addr.ipv4_mapped:
                addr=addr.ipv4_mapped
            found.append(addr)
        except ValueError:
            return None
    return found


def emit(**kwargs):
    print(FRAME+json.dumps(dict(
        AUDIT="BOUNDED_TCP_ONLY",CHANGED=False,HTTP_REQUESTS=0,
        MODEL_INFERENCE="NO",PAPERLESS_CHANGED="NO",
        OLLAMA_CONFIG_CHANGED="NO",FIREWALL_CHANGED="NO",
        NETWORK_EXPOSURE_GATE="REVIEW_REQUIRED",**kwargs
    ),sort_keys=True),flush=True)


def main():
    for ct,host in (("110","bergen-ai"),("126","bergen-paperless")):
        cfg=run(["pct","config",ct])
        state=run(["pct","status",ct],cap=100)
        if (not cfg or f"hostname: {host}" not in cfg.splitlines()
            or "unprivileged: 1" not in cfg.splitlines()
            or not state or state.strip()!="status: running"):
            emit(STATUS="GUEST_IDENTITY_UNVERIFIED")
            return
    dst=guest_address("110")
    ct126=guest_address("126")
    if not dst or not ct126:
        emit(STATUS="TARGET_OR_SOURCE_UNVERIFIED")
        return
    lxcroute=route("126",dst)
    podroute=route("126",dst,podman=True)
    if not lxcroute or not podroute:
        emit(STATUS="ROUTE_SOURCE_UNVERIFIED")
        return
    baseline=peers()
    if baseline is None:
        emit(STATUS="OLLAMA_SOCKET_INSPECTION_UNVERIFIED")
        return
    if baseline:
        emit(STATUS="OLLAMA_HAS_OTHER_TCP_CLIENTS",CONNECTION_CLASS="UNVERIFIED")
        return
    argv=["pct","exec","126","--","podman","exec","bergen-paperless",
          "python","-c",CONNECT_GUEST,dst]
    try:
        child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    except OSError:
        emit(STATUS="TCP_CLIENT_START_FAILED")
        return
    observed=None
    try:
        # The client holds its TCP socket for 8s, with no HTTP data.
        time.sleep(2)
        observed=peers()
        output,error=child.communicate(timeout=17)
        if child.returncode!=0 or len(output)>2400 or len(error)>4000:
            emit(STATUS="TCP_CLIENT_UNVERIFIED")
            return
        statuses=[json.loads(line.split(":",1)[1]).get("status")
                  for line in output.decode("utf-8","replace").splitlines()
                  if line.startswith("BERGEN_AI_SOURCE_CLIENT_V1:")]
        if statuses!=["HELD","CLOSED"]:
            emit(STATUS="TCP_CLIENT_UNVERIFIED")
            return
    except (subprocess.TimeoutExpired,ValueError,TypeError,UnicodeError):
        child.kill()
        child.communicate()
        emit(STATUS="TCP_OBSERVATION_UNVERIFIED")
        return
    if observed is None or len(observed)!=1:
        emit(STATUS="TCP_OBSERVATION_AMBIGUOUS",CONNECTION_CLASS="UNVERIFIED")
        return
    peer=observed[0]
    if peer.version!=4 or not peer.is_private or peer.is_loopback:
        emit(STATUS="TCP_PEER_UNEXPECTED",CONNECTION_CLASS="UNVERIFIED")
        return
    observed_ip=str(peer)
    if observed_ip==ct126:
        category="MATCHES_LXC126_PRIVATE_ADDRESS"
    elif observed_ip==lxcroute:
        category="MATCHES_LXC126_ROUTE_SOURCE"
    elif observed_ip==podroute:
        category="MATCHES_PODMAN_LOCAL_ROUTE"
    else:
        category="DIFFERENT_PRIVATE_PEER"
    emit(STATUS="SOURCE_OBSERVED",CONNECTION_CLASS=category,
         PODMAN_ROUTE_DIFFERS_FROM_LXC="YES" if podroute!=lxcroute else "NO",
         NAT_MECHANISM="NOT_DETERMINED",
         OBSERVED_ON="OLLAMA_LXC110",
         PORT=11434)


if __name__=="__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED")
