#!/usr/bin/env python3
"""Read-only, narrowly scoped vmbr90 apply preflight. Never modifies a host."""
import json
import re
import shutil
import subprocess
from pathlib import Path

FRAME = "BERGEN_AI_VMBR90_APPLY_PREFLIGHT_V1:"
TARGET = Path("/etc/network/interfaces.d/bergen-ai-vmbr90")


def run(argv, limit=50000):
    try:
        result = subprocess.run(argv, capture_output=True, check=False, timeout=15)
        return (result.stdout.decode("utf-8", "strict")
                if result.returncode == 0 and len(result.stdout) <= limit else None)
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def host_config():
    base = Path("/etc/network/interfaces")
    try:
        if not base.is_file() or base.is_symlink() or base.stat().st_size > 200000:
            return "UNVERIFIED"
        lines = base.read_text(encoding="utf-8").splitlines()
        sourced = any(re.fullmatch(
            r"\s*source\s+/etc/network/interfaces\.d/\*\s*(?:#.*)?", line)
            for line in lines)
        if not sourced:
            return "NO_EXPLICIT_SOURCE_GLOB"
        if Path("/etc/network/interfaces.new").exists():
            return "PENDING_PVE_NETWORK_EDIT"
        if Path("/root/bergen-ai-vmbr90-prechange").exists():
            return "ROLLBACK_EVIDENCE_DIR_ALREADY_EXISTS"
        if TARGET.is_symlink() or TARGET.exists():
            return "BRIDGE_DROPIN_ALREADY_PRESENT"
        if Path("/sys/class/net/vmbr90").exists():
            return "BRIDGE_ALREADY_PRESENT_IN_KERNEL"
        if (shutil.which("ifup") is None or
                shutil.which("ifquery") is None or
                shutil.which("ifreload") is None):
            return "IFUPDOWN2_TOOLING_UNVERIFIED"
        package = run(["dpkg-query", "-W", "-f=${Status}", "ifupdown2"])
        if package is None or "install ok installed" not in package:
            return "IFUPDOWN2_TOOLING_UNVERIFIED"
        return "EXPLICIT_SOURCE_NO_PENDING_EDIT"
    except (OSError, UnicodeError):
        return "UNVERIFIED"


def guest(vmid, hostname):
    raw = run(["pct", "config", str(vmid)])
    status = run(["pct", "status", str(vmid)], 200)
    if not raw or status is None or status.strip() != "status: running":
        return "UNVERIFIED"
    lines = raw.splitlines()
    if f"hostname: {hostname}" not in lines or "unprivileged: 1" not in lines:
        return "UNVERIFIED"
    entries = [line for line in lines if re.match(r"^net[0-9]+:\s", line)]
    if len(entries) != 1 or not entries[0].startswith("net0: "):
        return "UNEXPECTED_NETWORK_LAYOUT"
    if not re.search(r"(?:^|,)name=eth0(?:,|$)", entries[0][6:].strip()):
        return "UNEXPECTED_NETWORK_LAYOUT"
    if any("bridge=vmbr90" in line for line in lines):
        return "UNEXPECTED_NETWORK_LAYOUT"
    return "RUNNING_NET0_ONLY"


def report():
    host = host_config()
    a = guest(110, "bergen-ai")
    b = guest(126, "bergen-paperless")
    ready = host == "EXPLICIT_SOURCE_NO_PENDING_EDIT" and a == b == "RUNNING_NET0_ONLY"
    return dict(AUDIT="READ_ONLY", CHANGED=False,
                STATUS="SCOPED_HOST_PREFLIGHT_PASSED" if ready else "REVIEW_REQUIRED",
                HOST_NETWORK_SOURCE=host, CT110_NETWORK_LAYOUT=a,
                CT126_NETWORK_LAYOUT=b,
                NETWORK_CHANGES="NONE", OLLAMA_CHANGED=False,
                PAPERLESS_CHANGED=False, APPLY_AUTHORIZED=False)


def main():
    try:
        out = report()
    except Exception:
        out = dict(AUDIT="READ_ONLY", CHANGED=False,
                   STATUS="UNVERIFIED", HOST_NETWORK_SOURCE="UNVERIFIED",
                   CT110_NETWORK_LAYOUT="UNVERIFIED", CT126_NETWORK_LAYOUT="UNVERIFIED",
                   NETWORK_CHANGES="NONE", OLLAMA_CHANGED=False,
                   PAPERLESS_CHANGED=False, APPLY_AUTHORIZED=False)
    print(FRAME + json.dumps(out, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
