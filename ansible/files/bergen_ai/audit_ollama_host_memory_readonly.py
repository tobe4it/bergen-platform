#!/usr/bin/env python3
"""Read-only host-side cgroup v2 memory limit diagnostic for LXC 110.

Inspect Proxmox's exact /sys/fs/cgroup/lxc/110 host cgroup first. Fall back
to the container init host PID only where the standard PVE path is absent.
Read memory.max on the cgroup AND ancestors; the smallest finite
ancestor limit is the effective
cgroup ceiling. Guest-visible cgroup memory.max='max' is not authoritative.
No writes, restarts, model execution or document access.
"""
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

FRAME = "BERGEN_AI_GPU_HOST_MEMORY_V1:"
ROOT = Path("/sys/fs/cgroup")
TARGET_BYTES = 32768 * 1024 * 1024


def checked(argv, limit=12000, timeout=10):
    p = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
    if p.returncode != 0 or len(p.stdout) > limit:
        raise ValueError("HOST_COMMAND_UNVERIFIED")
    return p.stdout.decode("utf-8", errors="replace").strip()


def classify(limits):
    if not limits:
        return "NOT_VERIFIED"
    finite = [x for x in limits if isinstance(x, int)]
    if not finite:
        return "NO_FINITE_CGROUP_LIMIT"
    smallest = min(finite)
    if smallest == TARGET_BYTES:
        return "EFFECTIVE_32GIB"
    if smallest < TARGET_BYTES:
        return "BELOW_32GIB"
    return "ABOVE_32GIB"


def hierarchy(cgroup_path, root=ROOT):
    """Traverse only the host cgroup v2 ancestor chain, not other guests."""
    cg = PurePosixPath(cgroup_path)
    if not cgroup_path.startswith("/") or ".." in cg.parts:
        raise ValueError("INVALID_CGROUP_PATH")
    relative = cg.parts[1:]
    node = root.joinpath(*relative)
    resolved_root = root.resolve(strict=True)
    resolved_node = node.resolve(strict=True)
    if resolved_root not in resolved_node.parents and resolved_node != resolved_root:
        raise ValueError("CGROUP_ESCAPE")
    if not (resolved_root / "cgroup.controllers").is_file():
        raise ValueError("NOT_CGROUP_V2")
    values = []
    while True:
        file = node / "memory.max"
        if not file.is_file():
            raise ValueError("MEMORY_MAX_MISSING")
        raw = file.read_text(encoding="ascii").strip()
        if raw == "max":
            values.append(None)
        elif re.fullmatch(r"[0-9]{1,24}", raw):
            values.append(int(raw))
        else:
            raise ValueError("MEMORY_MAX_UNRECOGNIZED")
        if node == root:
            break
        node = node.parent
    return values


def main():
    cfg = checked(["pct", "config", "110"])
    expected = ("hostname: bergen-ai", "unprivileged: 1", "memory: 32768")
    if not all(line in cfg.splitlines() for line in expected):
        raise ValueError("LXC_WRONG_IDENTITY_OR_LIMIT")
    if checked(["pct", "status", "110"]) != "status: running":
        raise ValueError("LXC_NOT_RUNNING")
    # Proxmox 9 may not expose guest PID through standalone lxc-info,
    # despite the CT running under pct. Prefer its native host cgroup.
    direct = ROOT / "lxc" / "110"
    if (direct.is_dir() and not direct.is_symlink()
            and not (ROOT / "lxc").is_symlink()
            and (direct / "memory.max").is_file()):
        limits = hierarchy("/lxc/110")
        source = "PVE_LXC_110_CGROUP"
    else:
        # Secondary discovery for nonstandard PVE cgroup layouts.
        pidtext = checked(["lxc-info", "-n", "110", "-p", "-H"], limit=150)
        if not re.fullmatch(r"[1-9][0-9]{0,9}", pidtext):
            raise ValueError("LXC_PID_UNKNOWN")
        pid = int(pidtext)
        if pid == 1:
            raise ValueError("INVALID_CONTAINER_PID")
        cgroup_text = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii")
        unified = [line[len("0::"):] for line in cgroup_text.splitlines()
                   if line.startswith("0::")]
        if len(unified) != 1:
            raise ValueError("NO_UNIFIED_CGROUP")
        limits = hierarchy(unified[0])
        source = "INIT_PROCESS_HOST_CGROUP"
    status = classify(limits)
    print(FRAME+json.dumps({
        "AUDIT":"READ_ONLY", "CHANGED":False,
        "LXC110_CONFIGURED_32GIB":True,
        "LXC110_RUNNING":True,
        "HOST_CGROUP_V2":True,
        "CGROUP_LIMIT_STATUS":status,
        "CGROUP_SOURCE":source,
        "LEAF_MEMORY_LIMIT":"FINITE" if limits[0] is not None else "MAX",
        "FINITE_ANCESTOR_PRESENT":any(x is not None for x in limits[1:]),
        "INSPECTED_HIERARCHY_LEVELS":len(limits),
        "GPU_INFERENCE_PROVEN":False
    },sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(FRAME+json.dumps({
            "AUDIT":"READ_ONLY", "CHANGED":False,
            "CGROUP_LIMIT_STATUS":"UNVERIFIED",
            "GPU_INFERENCE_PROVEN":False
        },sort_keys=True))
        raise SystemExit(2)
