#!/usr/bin/env python3
"""Read-only, privacy-safe diagnostic after the first GPU-enabled LXC 110 reboot.

Unlike the strict postboot acceptance gate this emits independent reasons:
guest stopped/unreachable, each AMD device's mode/identity, Ollama service/API,
presence of the three pinned model tags, and effective memory.max category.
Never runs a model, restarts anything, or reads Paperless documents.
"""
import json
import re
import subprocess
import sys

PREFIX = "BERGEN_AI_GPU_DIAG_V1:"
MODELS = ("qwen2.5:14b-instruct-q4_K_M", "mistral-nemo:12b", "bge-m3:latest")

GUEST_PROBE = r'''
import json, os, pwd, stat, subprocess, urllib.request

def device(path, major, minor):
    try:
        s=os.stat(path)
        p=pwd.getpwnam("ollama")
        groups=set(os.getgrouplist("ollama",p.pw_gid))
        is_char=stat.S_ISCHR(s.st_mode)
        return {
          "present":True,
          "char_major_minor_ok":is_char and os.major(s.st_rdev)==major and os.minor(s.st_rdev)==minor,
          "uid_gid_ok":s.st_uid==999 and s.st_gid==992,
          "mode_0660":stat.S_IMODE(s.st_mode)==0o660,
          "ollama_owns_or_group_rw":(s.st_uid==p.pw_uid and bool(s.st_mode & 0o600 == 0o600))
              or (s.st_gid in groups and bool(s.st_mode & 0o060 == 0o060)),
          "uid":s.st_uid,"gid":s.st_gid,"mode":oct(stat.S_IMODE(s.st_mode)),
          "major":os.major(s.st_rdev) if is_char else -1,
          "minor":os.minor(s.st_rdev) if is_char else -1,
        }
    except (OSError, KeyError):
        return {"present":False}

try:
    p=pwd.getpwnam("ollama")
    ollama_account="PRESENT" if p.pw_uid==999 else "UNEXPECTED_UID"
except KeyError:
    ollama_account="ABSENT"

try:
    r=subprocess.run(["systemctl","is-active","ollama"],capture_output=True,timeout=5)
    value=r.stdout.decode("ascii","replace").strip()
    service=value if value in ("active","inactive","failed","activating","deactivating") else "UNKNOWN"
except (OSError,subprocess.TimeoutExpired):
    service="UNKNOWN"

api="UNREACHABLE"
names=set()
try:
    req=urllib.request.Request("http://127.0.0.1:11434/api/tags")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=6) as r:
        body=r.read(128001)
    if len(body)<=128000:
        parsed=json.loads(body)
        if isinstance(parsed.get("models"),list):
            api="OK"
            names={x.get("name") for x in parsed["models"] if isinstance(x,dict)
                   and isinstance(x.get("name"),str)}
except Exception:
    pass

try:
    value=open("/sys/fs/cgroup/memory.max","r",encoding="ascii").read(32).strip()
    if value==str(32768*1024*1024):
        memory="EXACT_32_GIB"
    elif value=="max":
        memory="MAX_UNLIMITED_VIEW"
    elif value.isdigit():
        memory="DIFFERENT_NUMERIC_LIMIT"
    else:
        memory="UNRECOGNIZED"
except OSError:
    memory="UNREADABLE"

out={
  "ollama_account":ollama_account,
  "render":device("/dev/dri/renderD128",226,128),
  "kfd":device("/dev/kfd",511,0),
  "ollama_service":service,
  "ollama_loopback_api":api,
  "qwen14_present":"qwen2.5:14b-instruct-q4_K_M" in names,
  "mistral12_present":"mistral-nemo:12b" in names,
  "bge_m3_present":"bge-m3:latest" in names,
  "cgroup_memory_max":memory,
}
print("BERGEN_AI_GPU_DIAG_GUEST_V1:"+json.dumps(out,sort_keys=True))
'''


def run(args, limit=10000, timeout=20):
    try:
        p=subprocess.run(args,capture_output=True,check=False,timeout=timeout)
        if len(p.stdout)>limit:
            return None
        return p
    except (OSError,subprocess.TimeoutExpired):
        return None


def main():
    result={
        "AUDIT":"READ_ONLY", "CHANGED":False,
        "LXC110_CONFIG":"UNVERIFIED",
        "LXC110_RUNTIME":"UNVERIFIED",
        "GUEST_PROBE":"NOT_RUN",
        "OLLAMA_ACCOUNT":"UNVERIFIED",
        "RENDER_PRESENT":False, "RENDER_CHAR_OK":False,
        "RENDER_OWNERSHIP_OK":False, "RENDER_MODE_OK":False,
        "RENDER_ACCESS_OK":False,
        "KFD_PRESENT":False, "KFD_CHAR_OK":False,
        "KFD_OWNERSHIP_OK":False,"KFD_MODE_OK":False,
        "KFD_ACCESS_OK":False,
        "OLLAMA_SERVICE":"UNVERIFIED", "OLLAMA_API":"UNVERIFIED",
        "QWEN14_PRESENT":False,"MISTRAL12_PRESENT":False,"BGE_M3_PRESENT":False,
        "CGROUP_MEMORY_MAX":"UNVERIFIED",
        "GPU_INFERENCE_PROVEN":False
    }
    cfg=run(["pct","config","110"])
    if cfg is None or cfg.returncode != 0:
        result["LXC110_CONFIG"]="UNREADABLE"
        print(PREFIX+json.dumps(result,sort_keys=True))
        return
    fields=dict(re.findall(r"(?m)^([\w]+):\s*([^\n]+)$",
                          cfg.stdout.decode("utf-8","replace")))
    if fields.get("hostname") != "bergen-ai" or fields.get("unprivileged") != "1":
        result["LXC110_CONFIG"]="WRONG_IDENTITY"
        print(PREFIX+json.dumps(result,sort_keys=True))
        return
    checks={
      "memory":"32768","cores":"18","swap":"2048",
      "dev0":"path=/dev/dri/renderD128,uid=999,gid=992,mode=0660",
      "dev1":"path=/dev/kfd,uid=999,gid=992,mode=0660"
    }
    result["LXC110_CONFIG"]="EXPECTED" if all(fields.get(k)==v for k,v in checks.items()) else "DRIFT"
    status=run(["pct","status","110"],limit=1000)
    result["LXC110_RUNTIME"]=(
        "RUNNING" if status is not None and status.returncode == 0
        and status.stdout.decode("ascii","replace").strip() == "status: running"
        else "NOT_CONFIRMED_RUNNING"
    )
    if result["LXC110_RUNTIME"] != "RUNNING":
        print(PREFIX+json.dumps(result,sort_keys=True))
        return
    guest=run(["pct","exec","110","--","python3","-c",GUEST_PROBE],
              limit=10000,timeout=35)
    if guest is None or guest.returncode != 0:
        result["GUEST_PROBE"]="EXEC_FAILED"
        print(PREFIX+json.dumps(result,sort_keys=True))
        return
    frames=[line[len("BERGEN_AI_GPU_DIAG_GUEST_V1:"):]
            for line in guest.stdout.decode("utf-8","replace").splitlines()
            if line.startswith("BERGEN_AI_GPU_DIAG_GUEST_V1:")]
    if len(frames)!=1 or len(frames[0])>3000:
        result["GUEST_PROBE"]="FRAME_INVALID"
        print(PREFIX+json.dumps(result,sort_keys=True))
        return
    data=json.loads(frames[0])
    expected={"ollama_account","render","kfd","ollama_service","ollama_loopback_api",
              "qwen14_present","mistral12_present","bge_m3_present","cgroup_memory_max"}
    if set(data)!=expected:
        result["GUEST_PROBE"]="FRAME_INVALID"
        print(PREFIX+json.dumps(result,sort_keys=True))
        return
    result["GUEST_PROBE"]="OK"
    result["OLLAMA_ACCOUNT"]=data["ollama_account"]
    for key,prefix in (("render","RENDER"),("kfd","KFD")):
        dev=data[key] if isinstance(data[key],dict) else {}
        for result_name,source_name in (
                ("PRESENT","present"),("CHAR_OK","char_major_minor_ok"),
                ("OWNERSHIP_OK","uid_gid_ok"),("MODE_OK","mode_0660"),
                ("ACCESS_OK","ollama_owns_or_group_rw")):
            result[prefix+"_"+result_name]=dev.get(source_name) is True
    result["OLLAMA_SERVICE"]=data["ollama_service"]
    result["OLLAMA_API"]=data["ollama_loopback_api"]
    result["QWEN14_PRESENT"]=data["qwen14_present"] is True
    result["MISTRAL12_PRESENT"]=data["mistral12_present"] is True
    result["BGE_M3_PRESENT"]=data["bge_m3_present"] is True
    result["CGROUP_MEMORY_MAX"]=data["cgroup_memory_max"]
    print(PREFIX+json.dumps(result,sort_keys=True))


if __name__=="__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        print(PREFIX+json.dumps({
          "AUDIT":"READ_ONLY","CHANGED":False,"LXC110_RUNTIME":"UNVERIFIED",
          "GUEST_PROBE":"DIAGNOSTIC_INVALID","GPU_INFERENCE_PROVEN":False
        },sort_keys=True))
        sys.exit(2)
