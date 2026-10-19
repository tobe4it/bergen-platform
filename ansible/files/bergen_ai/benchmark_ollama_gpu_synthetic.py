#!/usr/bin/env python3
"""One explicitly approved synthetic Qwen14B inference benchmark in existing LXC110.

This performs model inference, NOT a read-only audit. It never reads Paperless,
modifies service configuration, downloads models or changes PVE resources.
A bounded public-free synthetic German instruction is sent to loopback Ollama.
Only aggregate timing and /api/ps GPU allocation metrics are reported.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

FRAME="BERGEN_AI_GPU_BENCHMARK_V1:"
MODEL="qwen2.5:14b-instruct-q4_K_M"
MEM_BYTES=32768*1024*1024

GUEST_RUN = r'''
import json, urllib.request
MODEL="qwen2.5:14b-instruct-q4_K_M"
URL="http://127.0.0.1:11434"

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api(path, request=None, timeout=6):
    body=None if request is None else json.dumps(request).encode("utf-8")
    req=urllib.request.Request(URL+path,data=body,
                               headers={"Content-Type":"application/json"} if body else {})
    with opener.open(req,timeout=timeout) as resp:
        raw=resp.read(524289)
    if len(raw)>524288:
        raise ValueError("OVERSIZED_RESPONSE")
    return json.loads(raw)

names={x.get("name") for x in api("/api/tags").get("models",[])
       if isinstance(x,dict)}
if MODEL not in names:
    raise ValueError("MODEL_NOT_INSTALLED")
active=api("/api/ps").get("models",[])
if not isinstance(active,list) or len(active):
    raise ValueError("OLLAMA_BUSY")

body=api("/api/generate",{
    "model":MODEL,
    "prompt":"Antworte ausschließlich mit dem Wort OK.",
    "stream":False,
    "keep_alive":"45s",
    "options":{"num_predict":40,"num_ctx":2048,"temperature":0}
},timeout=240)

if body.get("model") != MODEL or body.get("done") is not True:
    raise ValueError("INFERENCE_NOT_COMPLETED")
count=body.get("eval_count")
duration=body.get("eval_duration")
if (type(count) is not int or count < 1 or count > 40
    or type(duration) is not int or duration <= 0):
    raise ValueError("INVALID_INFERENCE_METRICS")

running=api("/api/ps").get("models",[])
match=[x for x in running if isinstance(x,dict)
       and x.get("name")==MODEL] if isinstance(running,list) else []
vram=match[0].get("size_vram") if len(match)==1 else None
if type(vram) is int and vram>0:
    placement="GPU_ALLOCATION_OBSERVED"
elif vram==0:
    placement="CPU_ONLY_REPORTED"
else:
    placement="UNKNOWN"

report={
 "STATUS":"COMPLETED",
 "MODEL":MODEL,
 "EVAL_TOKENS":count,
 "GENERATE_TOKENS_PER_SECOND":round(count*1e9/duration,1),
 "LOAD_DURATION_SECONDS":round(body.get("load_duration",0)/1e9,2),
 "PROMPT_EVAL_TOKENS":body.get("prompt_eval_count",0),
 "GPU_PLACEMENT":placement,
 "GPU_ALLOCATED_GIB":round(vram/(1024**3),2) if type(vram) is int else None,
 "PROMPT_KIND":"SYNTHETIC_NO_DOCUMENTS",
 "SERVICE_CONFIGURATION_CHANGED":False
}
print("BERGEN_AI_GPU_BENCHMARK_GUEST_V1:"+json.dumps(report,sort_keys=True))
'''


def checked(argv,timeout=15,maxbytes=12000):
    run=subprocess.run(argv,capture_output=True,timeout=timeout,check=False)
    if run.returncode != 0 or len(run.stdout)>maxbytes:
        raise ValueError("COMMAND_UNVERIFIED")
    return run.stdout.decode("utf-8","replace").strip()


def main():
    config=checked(["pct","config","110"])
    lines=config.splitlines()
    exact=["hostname: bergen-ai","unprivileged: 1","memory: 32768",
           "cores: 18","swap: 2048",
           "dev0: path=/dev/dri/renderD128,uid=999,gid=992,mode=0660",
           "dev1: path=/dev/kfd,uid=999,gid=992,mode=0660"]
    if any(x not in lines for x in exact):
        raise ValueError("GUEST_CONFIG_DRIFT")
    if checked(["pct","status","110"])!="status: running":
        raise ValueError("GUEST_NOT_RUNNING")
    cgroup=Path("/sys/fs/cgroup/lxc/110/memory.max")
    if (not cgroup.is_file() or cgroup.is_symlink()
        or cgroup.read_text(encoding="ascii").strip()!=str(MEM_BYTES)):
        raise ValueError("HOST_CGROUP_NOT_32GIB")
    mem=Path("/proc/meminfo").read_text(encoding="ascii")
    matches=re.findall(r"(?m)^MemAvailable:\s+([0-9]+)\s+kB$",mem)
    if len(matches)!=1 or int(matches[0])<16*1024*1024:
        raise ValueError("HOST_AVAILABLE_MEMORY_TOO_LOW")

    response=checked(["pct","exec","110","--","python3","-c",GUEST_RUN],
                     timeout=275,maxbytes=5000)
    frames=[x[len("BERGEN_AI_GPU_BENCHMARK_GUEST_V1:"):]
            for x in response.splitlines()
            if x.startswith("BERGEN_AI_GPU_BENCHMARK_GUEST_V1:")]
    if len(frames)!=1 or len(frames[0])>2500:
        raise ValueError("INFERENCE_FRAME_INVALID")
    data=json.loads(frames[0])
    expected={"STATUS","MODEL","EVAL_TOKENS","GENERATE_TOKENS_PER_SECOND",
              "LOAD_DURATION_SECONDS","PROMPT_EVAL_TOKENS",
              "GPU_PLACEMENT","GPU_ALLOCATED_GIB","PROMPT_KIND",
              "SERVICE_CONFIGURATION_CHANGED"}
    if set(data)!=expected or data["STATUS"]!="COMPLETED" or data["MODEL"]!=MODEL:
        raise ValueError("INFERENCE_FRAME_INVALID")
    if (data["PROMPT_KIND"]!="SYNTHETIC_NO_DOCUMENTS"
        or data["SERVICE_CONFIGURATION_CHANGED"] is not False
        or data["GPU_PLACEMENT"] not in (
          "GPU_ALLOCATION_OBSERVED","CPU_ONLY_REPORTED","UNKNOWN")):
        raise ValueError("INFERENCE_FRAME_INVALID")
    print(FRAME+json.dumps({
      "STATUS":"SYNTHETIC_COMPLETED",
      "MODEL":MODEL,
      "PROMPT_KIND":data["PROMPT_KIND"],
      "EVAL_TOKENS":data["EVAL_TOKENS"],
      "TOKENS_PER_SECOND":data["GENERATE_TOKENS_PER_SECOND"],
      "LOAD_SECONDS":data["LOAD_DURATION_SECONDS"],
      "GPU_PLACEMENT":data["GPU_PLACEMENT"],
      "GPU_ALLOCATED_GIB":data["GPU_ALLOCATED_GIB"],
      "CONFIGURATION_CHANGED":False,
      "PAPERLESS_CHANGED":False
    },sort_keys=True))


if __name__=="__main__":
    try:
        main()
    except Exception:
        print(FRAME+json.dumps({
          "STATUS":"BENCHMARK_UNVERIFIED","CONFIGURATION_CHANGED":False,
          "PAPERLESS_CHANGED":False
        },sort_keys=True))
        sys.exit(2)
