#!/usr/bin/env python3
"""Sanitized safe model-installation plan from the existing LXC110 Ollama API.

Read-only: uses only loopback /api/tags and statvfs of the existing model
path. Explicit sizes are conservative provision estimates, not a claim
about current filesystem allocation. No installation or deletion.
"""
import json
import os
from pathlib import Path
import re
import urllib.request

FRAME = "BERGEN_AI_MODEL_PLAN_V1:"
SIZES_GIB = {
    "qwen2.5:14b-instruct-q4_K_M": 10,
    "mistral-nemo:12b": 8,
    "llama3.1:8b": 6,
    "bge-m3": 2,
    "qwen2.5:32b-instruct-q4_K_M": 22,
}

def read_local_models():
    req=urllib.request.Request("http://127.0.0.1:11434/api/tags")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as r:
        raw=r.read(128001)
    if len(raw)>128000:
        raise ValueError("MODEL_FRAME_TOO_LARGE")
    models=json.loads(raw).get("models", [])
    if not isinstance(models,list) or len(models)>300:
        raise ValueError("MODEL_FRAME_INVALID")
    return {m.get("name") for m in models if isinstance(m,dict)
            and isinstance(m.get("name"),str)
            and re.fullmatch(r"[A-Za-z0-9._:/-]{1,96}", m.get("name"))}

def plan(request):
    if request.get("protocol")!="v1" or not isinstance(request.get("models"),list):
        raise ValueError("BAD_REQUEST")
    requested=request["models"]
    if not requested or len(requested)>4 or len(requested)!=len(set(requested)):
        raise ValueError("BAD_MODEL_COUNT")
    if any(x not in SIZES_GIB for x in requested):
        raise ValueError("UNAPPROVED_MODEL")
    if "qwen2.5:32b-instruct-q4_K_M" in requested and not request.get("large_model_review"):
        raise ValueError("LARGE_MODEL_GATE")
    model_path=Path("/srv/ai/models")
    if not model_path.is_dir() or model_path.is_symlink():
        raise ValueError("MODEL_PATH_INVALID")
    stat=os.statvfs(model_path)
    free=stat.f_bavail*stat.f_frsize/(1024**3)
    installed=read_local_models()
    missing=[m for m in requested if m not in installed]
    need=sum(SIZES_GIB[m] for m in missing)+15
    return dict(
      AUDIT="READ_ONLY", CHANGED=False,
      STATUS="READY_FOR_EXPLICIT_APPROVAL" if free >= need else "DISK_CAPACITY_LOW",
      MISSING=missing,
      MODEL_PATH="/srv/ai/models", FREE_GIB=round(free,1),
      MINIMUM_FREE_FOR_PULL_GIB=need,
      LARGE_REQUESTED="qwen2.5:32b-instruct-q4_K_M" in requested,
    )

if __name__=="__main__":
    import sys
    try:
        out=plan(json.load(sys.stdin))
        print(FRAME+json.dumps(out,sort_keys=True))
    except Exception:
        print(FRAME+json.dumps(dict(AUDIT="READ_ONLY",CHANGED=False,
                                    STATUS="UNVERIFIED",MISSING=[])))
        raise SystemExit(2)
