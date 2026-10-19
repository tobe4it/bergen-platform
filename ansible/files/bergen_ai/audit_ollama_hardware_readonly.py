#!/usr/bin/env python3
"""Read-only, non-identifying venombox LXC 110/126 Ollama/GPU preflight.

Runs solely on reviewed Proxmox host via existing Ansible inventory.
No privileged container conversion, persistent config, service restart,
network exposure, GPU bindings, image pulls or model execution.
Emits exactly one short, bounded JSON classification frame.
"""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

FRAME = "BERGEN_AI_MODEL_PREFLIGHT_V1:"
EXPECTED = {110: "bergen-ai", 126: "bergen-paperless"}


class AuditError(Exception):
    pass


def demand(ok, code):
    if not ok:
        raise AuditError(code)


def run(argv, max_bytes=30000, timeout=15):
    p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    demand(p.returncode == 0 and len(p.stdout) <= max_bytes, "COMMAND_UNAVAILABLE")
    return p.stdout.decode("utf-8", errors="replace")


def parse_pct(text, name):
    fields = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fields[k.strip()] = v.strip()
    demand(fields.get("hostname") == name, "LXC_IDENTITY_MISMATCH")
    demand(fields.get("unprivileged") == "1", "UNPRIVILEGED_REQUIRED")
    ram = fields.get("memory", "")
    demand(ram.isdecimal() and 256 <= int(ram) <= 262144, "LXC_RAM_UNVERIFIED")
    return {
        "memory_mib": int(ram),
        "swap_mib": int(fields.get("swap", "0")) if fields.get("swap", "0").isdecimal() else -1,
        "cores": int(fields.get("cores", "0")) if fields.get("cores", "0").isdecimal() else -1,
        "running": False,
        "gpu_config": any(
            ("dev/dri" in x or "dev/kfd" in x) and
            (x.startswith("lxc.mount.entry:") or re.match(r"dev[0-9]+:", x))
            for x in text.splitlines()
        ),
    }


GUEST_SCRIPT = r'''
import json, os, re, shutil, stat, urllib.request
from pathlib import Path
def gpu(path):
    try:
        s=os.stat(path)
        return {
            "exists": stat.S_ISCHR(s.st_mode),
            "major": os.major(s.st_rdev),
            "minor": os.minor(s.st_rdev),
            "gid": s.st_gid,
            "readable": os.access(path, os.R_OK|os.W_OK),
        }
    except OSError:
        return {"exists": False}
def disk(path):
    try:
        d=shutil.disk_usage(path)
        return round(d.free/(1024**3), 1)
    except OSError:
        return -1
def models():
    try:
        req=urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=4) as r:
            b=r.read(128001)
        if len(b)>128000: return {"api":"UNVERIFIED", "names":[]}
        v=json.loads(b)
        if not isinstance(v.get("models"),list): return {"api":"UNVERIFIED","names":[]}
        n=sorted({m["name"] for m in v["models"] if isinstance(m,dict)
          and isinstance(m.get("name"),str)
          and re.fullmatch(r"[a-zA-Z0-9._:/-]{1,96}",m["name"])})
        return {"api":"LOOPBACK_OK", "names":n[:50]}
    except Exception:
        return {"api":"UNREACHABLE", "names":[]}
print(json.dumps({
 "dri_render":gpu("/dev/dri/renderD128"),
 "kfd":gpu("/dev/kfd"),
 "models":models(),
 "model_disk_free_gib":disk("/srv/ai/models"),
 "guest_root_free_gib":disk("/"),
},sort_keys=True))
'''


def guest_inventory(vmid):
    raw = run(["pct", "exec", str(vmid), "--", "python3", "-c", GUEST_SCRIPT],
              max_bytes=25000, timeout=20)
    data = json.loads(raw.strip())
    demand(set(data) == {"dri_render", "kfd", "models",
                         "model_disk_free_gib", "guest_root_free_gib"},
           "GUEST_FRAME_INVALID")
    return data


def char_device(path):
    try:
        s = os.stat(path)
        return {
            "exists": stat.S_ISCHR(s.st_mode),
            "major": os.major(s.st_rdev),
            "minor": os.minor(s.st_rdev),
            "gid": s.st_gid,
        }
    except OSError:
        return {"exists": False}


def mem_available_mib():
    m = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            try:
                m[k] = int(v.strip().split()[0])
            except (ValueError, IndexError):
                pass
    demand("MemTotal" in m and "MemAvailable" in m, "MEMORY_UNAVAILABLE")
    return int(m["MemTotal"] / 1024), int(m["MemAvailable"] / 1024)


def audit():
    demand(Path("/etc/pve/lxc").is_dir(), "NOT_PROXMOX_HOST")
    guests = {}
    for vmid, hostname in EXPECTED.items():
        cfg = run(["pct", "config", str(vmid)])
        info = parse_pct(cfg, hostname)
        info["running"] = run(["pct", "status", str(vmid)]).strip() == "status: running"
        demand(info["running"], "LXC_NOT_RUNNING")
        guests[vmid] = info
    cpu = Path("/proc/cpuinfo").read_text(errors="replace")
    total, available = mem_available_mib()
    host_render = char_device("/dev/dri/renderD128")
    host_kfd = char_device("/dev/kfd")
    ai = guest_inventory(110)
    # No actual performance/GPU-offload claim without inference telemetry.
    report = {
        "AUDIT": "READ_ONLY",
        "CHANGED": False,
        "PVE_CPU_EXPECTED_HX370": "YES" if "Ryzen AI 9 HX 370" in cpu else "UNVERIFIED",
        "HOST_MEMORY_MIB": total,
        "HOST_AVAILABLE_MIB": available,
        "LXC110_UNPRIVILEGED": "YES",
        "LXC110_MEMORY_MIB": guests[110]["memory_mib"],
        "LXC110_SWAP_MIB": guests[110]["swap_mib"],
        "LXC110_CORES": guests[110]["cores"],
        "LXC110_GPU_CONFIG_PRESENT": guests[110]["gpu_config"],
        "LXC126_UNPRIVILEGED": "YES",
        "LXC126_MEMORY_MIB": guests[126]["memory_mib"],
        "LXC126_CORES": guests[126]["cores"],
        "HOST_RENDER": host_render,
        "HOST_KFD": host_kfd,
        "GUEST_RENDER": ai["dri_render"],
        "GUEST_KFD": ai["kfd"],
        "OLLAMA": ai["models"]["api"],
        "MODELS": ai["models"]["names"],
        "MODEL_DISK_FREE_GIB": ai["model_disk_free_gib"],
        "GUEST_ROOT_FREE_GIB": ai["guest_root_free_gib"],
        "GPU_INFERENCE_PROVEN": "NO",
        "PAPERLESS_CONNECTIVITY_PROVEN": "NO",
    }
    demand(len(report["MODELS"]) <= 50, "MODEL_COUNT_UNVERIFIED")
    print(FRAME + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    try:
        audit()
    except (AuditError, OSError, ValueError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        print(FRAME + json.dumps({"AUDIT": "READ_ONLY",
                                  "CHANGED": False,
                                  "STATUS": "UNVERIFIED"}, sort_keys=True))
        sys.exit(2)
