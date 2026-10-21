"""Verify existing Bergen-AI LXC 110 device and Ollama readiness after reboot.

Read-only; no model inference or Paperless access. Designed for Proxmox host.
All output is short and non-identifying. Does not establish GPU compute use.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

FRAME = "BERGEN_AI_GPU_POSTBOOT_V1:"

EXPECTED_DEVICES = {
    "dev0": "path=/dev/dri/renderD128,uid=999,gid=992,mode=0660",
    "dev1": "path=/dev/kfd,uid=999,gid=992,mode=0660",
}
EXPECTED_MODELS = {
    "qwen2.5:14b-instruct-q4_K_M",
    "mistral-nemo:12b",
    "bge-m3:latest",
}

GUEST_READ = r'''
import grp, json, os, pwd, stat, subprocess, urllib.request
expected = {
  "/dev/dri/renderD128": (226, 128),
  "/dev/kfd": (511, 0),
}
p = pwd.getpwnam("ollama")
groups = set(os.getgrouplist("ollama", p.pw_gid))
devs = {}
for path,(major,minor) in expected.items():
    try:
        s = os.stat(path)
        isdevice = stat.S_ISCHR(s.st_mode)
        has_rw = ((s.st_uid == p.pw_uid and s.st_mode & 0o600 == 0o600)
                  or (s.st_gid in groups and s.st_mode & 0o060 == 0o060))
        devs[path] = (isdevice and os.major(s.st_rdev)==major
                      and os.minor(s.st_rdev)==minor and
                      s.st_uid==p.pw_uid and s.st_gid==992 and
                      stat.S_IMODE(s.st_mode)==0o660 and bool(has_rw))
    except OSError:
        devs[path] = False
try:
    active = subprocess.run(["systemctl", "is-active", "--quiet", "ollama"],
                            check=False,timeout=5).returncode == 0
except (OSError, subprocess.TimeoutExpired):
    active = False
models = []
try:
    req=urllib.request.Request("http://127.0.0.1:11434/api/tags")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as r:
        data=r.read(128001)
    if len(data)<=128000:
        models = [x["name"] for x in json.loads(data).get("models",[])
                  if isinstance(x,dict) and isinstance(x.get("name"),str)]
except Exception:
    pass
try:
    memory_limit = open("/sys/fs/cgroup/memory.max").read().strip()
except OSError:
    memory_limit = "UNREADABLE"
print("BERGEN_AI_GPU_GUEST_V1:"+json.dumps({
  "devices_ok": all(devs.values()),
  "ollama_active": active,
  "ollama_api": bool(models),
  "models": [m for m in models if m in
             ["qwen2.5:14b-instruct-q4_K_M","mistral-nemo:12b","bge-m3:latest"]],
  "memory_limit": memory_limit,
},sort_keys=True))
'''


def run(*args, timeout=20):
    proc = subprocess.run(list(args), capture_output=True, check=False, timeout=timeout)
    if proc.returncode != 0 or len(proc.stdout) > 32000:
        raise ValueError("COMMAND_FAILED")
    return proc.stdout.decode("utf-8", errors="replace")


def main():
    cfg = run("pct", "config", "110")
    values = dict((name, value.strip()) for name, value in
                  re.findall(r"(?m)^([\w]+):\s*([^\n]+)$",cfg))
    if any(values.get(name) != value for name, value in
           (("hostname","bergen-ai"),("unprivileged","1"),
            ("memory","32768"),("cores","18"),("swap","2048"))):
        raise ValueError("CONFIG_DRIFT")
    if any(values.get(slot) != spec for slot, spec in EXPECTED_DEVICES.items()):
        raise ValueError("DEVICE_CONFIG_DRIFT")
    if run("pct","status","110").strip() != "status: running":
        raise ValueError("GUEST_OFFLINE")
    result=run("pct","exec","110","--","python3","-c",GUEST_READ,timeout=25)
    frames=[x[len("BERGEN_AI_GPU_GUEST_V1:"):] for x in result.splitlines()
            if x.startswith("BERGEN_AI_GPU_GUEST_V1:")]
    if len(frames) != 1 or len(frames[0]) > 2000:
        raise ValueError("GUEST_FRAME_INVALID")
    data=json.loads(frames[0])
    if set(data) != {"devices_ok","ollama_active","ollama_api","models","memory_limit"}:
        raise ValueError("GUEST_FRAME_INVALID")
    # Proxmox enforces the limit on its host cgroup. The guest's
    # cgroup-namespace root is not authoritative and may report 'max'.
    cgroup_file=Path("/sys/fs/cgroup/lxc/110/memory.max")
    host_memory_ok=(cgroup_file.is_file() and not cgroup_file.is_symlink()
                    and cgroup_file.read_text(encoding="ascii").strip()
                    == str(32768*1024*1024))
    good=(data["devices_ok"] is True and data["ollama_active"] is True
          and data["ollama_api"] is True
          and set(data["models"]) == EXPECTED_MODELS
          and host_memory_ok)
    print(FRAME+json.dumps({
      "AUDIT":"READ_ONLY", "CHANGED":False,
      "STATUS":"READY_FOR_SYNTHETIC_INFERENCE" if good else "NOT_READY",
      "LXC110_RUNNING":True,
      "GPU_DEVICE_ACCESS_OK":data["devices_ok"],
      "OLLAMA_ACTIVE":data["ollama_active"],
      "OLLAMA_LOOPBACK_OK":data["ollama_api"],
      "THREE_MODELS_PRESENT":set(data["models"])==EXPECTED_MODELS,
      "MEMORY_CGROUP_32G_OK":host_memory_ok,
      "MEMORY_CHECK_SOURCE":"PVE_HOST_LXC_110_CGROUP",
      "GPU_COMPUTE_VERIFIED":False
    },sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(FRAME+json.dumps({
          "AUDIT":"READ_ONLY","CHANGED":False,
          "STATUS":"UNVERIFIED","GPU_COMPUTE_VERIFIED":False
        },sort_keys=True))
        sys.exit(2)
