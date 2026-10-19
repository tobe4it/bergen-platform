"""Issue #115: one-time read-only GPU stage readiness for existing LXC 110.

Inspects exact host devices, current Proxmox device definitions, guest render
group/Ollama account membership and effective LXC quota. No writes.
"""
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys

FRAME = "BERGEN_AI_GPU_STAGE_V1:"
GPU_DEVICES = {
    "/dev/dri/renderD128": (226, 128),
    "/dev/kfd": (511, 0),
}


def checked(args, timeout=12):
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout, check=True)
    text = proc.stdout.decode("utf-8", errors="replace")
    if len(text) > 32000:
        raise ValueError("OUTPUT_TOO_LARGE")
    return text


def get_lxc():
    cfg = checked(["pct", "config", "110"])
    assert re.search(r"(?m)^hostname:\s*bergen-ai\s*$", cfg)
    assert re.search(r"(?m)^unprivileged:\s*1\s*$", cfg)
    assert "lxc.apparmor.profile: unconfined" not in cfg
    values = dict(m.groups() for m in
                  re.finditer(r"(?m)^([a-z][\w]*):\s*([^\n]+)$", cfg))
    assert values.get("memory", "").isdigit()
    assert checked(["pct", "status", "110"]).strip() == "status: running"
    lines = cfg.splitlines()
    assert not any(re.match(r"^dev\d+:", s) for s in lines)
    assert not any(s.startswith("lxc.idmap:") for s in lines)
    assert not any("dev/dri" in s or "dev/kfd" in s for s in lines)
    return {"memory": int(values["memory"]),
            "swap": int(values.get("swap", "-1")) if values.get("swap", "").isdigit() else -1,
            "cores": int(values.get("cores", "0")) if values.get("cores", "").isdigit() else 0}


def devinfo():
    infos = {}
    for name, expected in GPU_DEVICES.items():
        s = os.stat(name)
        assert stat.S_ISCHR(s.st_mode)
        assert (os.major(s.st_rdev), os.minor(s.st_rdev)) == expected
        infos[name] = {"major": expected[0], "minor": expected[1], "host_gid": s.st_gid}
    return infos


GUEST_READ = r'''
import grp,json,pwd
p=pwd.getpwnam("ollama")
render=grp.getgrnam("render")
video=grp.getgrnam("video")
groups=list(map(int, __import__("os").getgrouplist("ollama", p.pw_gid)))
print("BERGEN_GPU_GUEST_V1:"+json.dumps({
  "render_gid":render.gr_gid,"video_gid":video.gr_gid,
  "ollama_uid":p.pw_uid,
  "ollama_in_render":render.gr_gid in groups
},sort_keys=True))
'''


def guest_info():
    data = checked(["pct", "exec", "110", "--", "python3", "-c", GUEST_READ])
    lines = [line.split("BERGEN_GPU_GUEST_V1:", 1)[1] for line in data.splitlines()
             if line.startswith("BERGEN_GPU_GUEST_V1:")]
    assert len(lines) == 1
    val = json.loads(lines[0])
    assert set(val) == {"render_gid","video_gid","ollama_uid","ollama_in_render"}
    assert type(val["render_gid"]) is int and 1 <= val["render_gid"] <= 65535
    assert type(val["ollama_uid"]) is int and val["ollama_uid"] > 0
    return val


def main():
    info = get_lxc()
    devices = devinfo()
    guest = guest_info()
    pve = checked(["pct", "help", "set"])
    assert "--dev[n]" in pve or "--dev0" in pve or "--dev[n]" in pve.replace(" ", "")
    assert info["memory"] == 16384  # no silent redo of a different baseline
    # Only stage a change against the exact measured version.
    print(FRAME + json.dumps({
        "AUDIT": "READ_ONLY", "CHANGED": False, "STATUS": "READY_FOR_REVIEW",
        "LXC_MEMORY_MIB": info["memory"], "LXC_CORES": info["cores"],
        "TARGET_MEMORY_MIB": 32768,
        "RENDER_HOST_GID": devices["/dev/dri/renderD128"]["host_gid"],
        "KFD_HOST_GID": devices["/dev/kfd"]["host_gid"],
        "GUEST_RENDER_GID": guest["render_gid"],
        "GUEST_OLLAMA_UID": guest["ollama_uid"],
        "OLLAMA_MEMBER_OF_RENDER": guest["ollama_in_render"],
        "PASSTHROUGH_METHOD": "PROXMOX_DEV0_DEV1",
        "RESTART_REQUIRED_FOR_GPU": True,
    },sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(FRAME + json.dumps({"AUDIT":"READ_ONLY","CHANGED":False,
                                  "STATUS":"UNVERIFIED"}))
        sys.exit(2)
