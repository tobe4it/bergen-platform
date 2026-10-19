#!/usr/bin/env python3
"""Check only native Paperless Podman container -> existing Bergen-AI Ollama LXC.

READ ONLY: no Ollama inference, model pull, Paperless ORM writes, config,
mount changes, firewall changes or service restarts. Never print addresses.
Any network destination is first discovered inside the verified LXC110 guest.
"""
import ipaddress
import json
import subprocess

FRAME = "BERGEN_PAPERLESS_OLLAMA_PATH_V1:"
EXPECTED_MODEL = "qwen2.5:14b-instruct-q4_K_M"

GUEST_DISCOVER = r'''
import ipaddress,json,subprocess
try:
    r=subprocess.run(["ip","-j","-4","addr","show"],capture_output=True,
                     check=False,timeout=5)
    if r.returncode!=0 or len(r.stdout)>50000:
        raise ValueError("IP_INVENTORY_FAILED")
    interfaces=json.loads(r.stdout)
    addresses=set()
    for interface in interfaces:
        if interface.get("ifname")=="lo":
            continue
        for item in interface.get("addr_info",[]):
            if item.get("family")!="inet":
                continue
            a=ipaddress.ip_address(item.get("local",""))
            if (a.version==4 and a.is_private and not a.is_loopback
                and not a.is_link_local and not a.is_unspecified
                and not a.is_multicast):
                addresses.add(str(a))
    r=subprocess.run(["ss","-H","-ltn"],capture_output=True,check=False,timeout=5)
    if r.returncode!=0 or len(r.stdout)>32000:
        raise ValueError("LISTENER_INVENTORY_FAILED")
    listeners=[]
    for line in r.stdout.decode("ascii","replace").splitlines():
        fields=line.split()
        if len(fields)>=4:
            addr=fields[3]
            if addr.rsplit(":",1)[-1]=="11434":
                listeners.append(addr)
    if not listeners:
        scope="NONE"
    elif any(x.startswith(("0.0.0.0:","*:","[::]:",":::")) for x in listeners):
        scope="WILDCARD"
    elif all(x.startswith(("127.","[::1]:","::1:")) for x in listeners):
        scope="LOOPBACK_ONLY"
    else:
        scope="INTERFACE_OR_MIXED"
    print("BERGEN_PAPERLESS_OLLAMA_NET_GUEST_V1:"+json.dumps({
        "candidates":sorted(addresses),
        "listener_scope":scope
    },sort_keys=True))
except Exception:
    print("BERGEN_PAPERLESS_OLLAMA_NET_GUEST_V1:"+json.dumps({
        "candidates":[],"listener_scope":"UNVERIFIED"
    },sort_keys=True))
'''

PAPERLESS_PROBE = r'''
import json,sys,urllib.request
address=sys.argv[1]
model="qwen2.5:14b-instruct-q4_K_M"
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,url):
        return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
state="UNREACHABLE"
try:
    req=urllib.request.Request("http://"+address+":11434/api/tags",
                              headers={"Accept":"application/json"},method="GET")
    with opener.open(req,timeout=5) as response:
        if response.status!=200:
            raise ValueError("NON_200")
        body=response.read(256001)
    if len(body)>256000:
        raise ValueError("RESPONSE_OVERSIZED")
    models=json.loads(body).get("models")
    if not isinstance(models,list) or len(models)>300:
        raise ValueError("MODELS_INVALID")
    state=("MODEL_PRESENT" if any(
        isinstance(m,dict) and m.get("name")==model for m in models
    ) else "MODEL_ABSENT")
except Exception:
    pass
print("BERGEN_PAPERLESS_OLLAMA_NET_PODMAN_V1:"+json.dumps({
    "status":state
},sort_keys=True))
'''


def command(argv, timeout=25, maxbytes=12000):
    try:
        result=subprocess.run(argv,capture_output=True,check=False,timeout=timeout)
        if result.returncode!=0 or len(result.stdout)>maxbytes:
            return ""
        return result.stdout.decode("utf-8","replace")
    except (OSError,subprocess.TimeoutExpired):
        return ""


def frame(text, prefix):
    lines=[line[len(prefix):] for line in text.splitlines()
           if line.startswith(prefix)]
    if len(lines)!=1 or len(lines[0])>2400:
        return None
    try:
        return json.loads(lines[0])
    except (ValueError,TypeError):
        return None


def emit(**values):
    print(FRAME+json.dumps(dict(AUDIT="READ_ONLY",CHANGED=False,**values),
                           sort_keys=True),flush=True)


def main():
    for ct,hostname in (("110","bergen-ai"),("126","bergen-paperless")):
        cfg=command(["pct","config",ct])
        if (not cfg or f"hostname: {hostname}" not in cfg.splitlines()
                or "unprivileged: 1" not in cfg.splitlines()
                or "lxc.apparmor.profile: unconfined" in cfg.splitlines()):
            emit(STATUS="UNVERIFIED_GUEST_IDENTITY",OLLAMA_LISTENER="UNVERIFIED",
                 MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
            return
        if command(["pct","status",ct]).strip()!="status: running":
            emit(STATUS="GUEST_NOT_RUNNING",OLLAMA_LISTENER="UNVERIFIED",
                 MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
            return
    info=frame(command(["pct","exec","110","--","python3","-c",GUEST_DISCOVER],
                       timeout=22),
               "BERGEN_PAPERLESS_OLLAMA_NET_GUEST_V1:")
    if not isinstance(info,dict) or set(info)!={"candidates","listener_scope"}:
        emit(STATUS="GUEST_NETWORK_INSPECTION_FAILED",OLLAMA_LISTENER="UNVERIFIED",
             MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
        return
    scope=info["listener_scope"]
    if scope not in ("NONE","WILDCARD","LOOPBACK_ONLY",
                     "INTERFACE_OR_MIXED","UNVERIFIED"):
        emit(STATUS="GUEST_NETWORK_INSPECTION_FAILED",OLLAMA_LISTENER="UNVERIFIED",
             MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
        return
    addresses=info["candidates"]
    if not isinstance(addresses,list) or len(addresses)>12:
        emit(STATUS="GUEST_NETWORK_INSPECTION_FAILED",OLLAMA_LISTENER=scope,
             MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
        return
    try:
        if len(set(addresses))!=len(addresses):
            raise ValueError("DUPLICATE")
        for candidate in addresses:
            a=ipaddress.ip_address(candidate)
            if not (a.version==4 and a.is_private and not a.is_loopback
                    and not a.is_link_local and not a.is_unspecified
                    and not a.is_multicast):
                raise ValueError("NON_PRIVATE")
    except (ValueError,TypeError):
        emit(STATUS="GUEST_NETWORK_INSPECTION_FAILED",OLLAMA_LISTENER=scope,
             MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
        return
    if len(addresses)!=1:
        emit(STATUS="REVIEW_PRIVATE_IPV4_SELECTION",OLLAMA_LISTENER=scope,
             MODEL_FROM_PAPERLESS="UNVERIFIED",
             CANDIDATE_PRIVATE_IPV4="NONE" if not addresses else "MULTIPLE")
        return
    if scope in ("NONE","LOOPBACK_ONLY","UNVERIFIED"):
        emit(STATUS="OLLAMA_NOT_BOUND_TO_PRIVATE_INTERFACE",OLLAMA_LISTENER=scope,
             MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="ONE")
        return
    response=frame(command([
        "pct","exec","126","--","podman","exec","bergen-paperless",
        "python","-c",PAPERLESS_PROBE,addresses[0]
    ],timeout=24),"BERGEN_PAPERLESS_OLLAMA_NET_PODMAN_V1:")
    status=response.get("status") if isinstance(response,dict) else None
    if status not in ("MODEL_PRESENT","MODEL_ABSENT","UNREACHABLE"):
        status="PROBE_UNVERIFIED"
    emit(STATUS="PAPERLESS_PRIVATE_PATH_READY" if status=="MODEL_PRESENT" else
        "PAPERLESS_PRIVATE_PATH_NOT_READY",
        OLLAMA_LISTENER=scope,
        CANDIDATE_PRIVATE_IPV4="ONE",
        MODEL_FROM_PAPERLESS=status,
        ENDPOINT_APPROVED_FOR_APPLY=False,
        NETWORK_EXPOSURE_REVIEW="REQUIRED" if scope=="WILDCARD" else "RECOMMENDED")


if __name__=="__main__":
    try:
        main()
    except Exception:
        emit(STATUS="UNVERIFIED",OLLAMA_LISTENER="UNVERIFIED",
             MODEL_FROM_PAPERLESS="UNVERIFIED",CANDIDATE_PRIVATE_IPV4="UNVERIFIED")
