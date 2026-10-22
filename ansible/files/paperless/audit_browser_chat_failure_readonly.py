"""Sanitized no-write CT125 Nginx and CT126 Paperless chat error audit.

Bounded after browser-failed test at 2026-10-22 09:54 UTC.
Never emit response text, prompts, filenames, document IDs, URLs,
cookies, user identities, raw HTTP logs, container stderr or traceback.
"""
import json
import re
import subprocess

FRAME = "BERGEN_PAPERLESS_CHAT_BROWSER_FAILURE_V1:"
DATE = "22/Oct/2026"
HOURS = ("09", "10")
FROM_UTC = "2026-10-22T09:40:00Z"
TO_UTC = "2026-10-22T10:20:00Z"

PROXY_INSPECT = r'''
from pathlib import Path
import json
import re
import socket
if socket.gethostname().split(".")[0] != "bergen-proxy":
    raise SystemExit("PROXY_IDENTITY_MISMATCH")
paths = sorted(Path("/var/log/nginx").glob("*access*.log"))
errorpaths = sorted(Path("/var/log/nginx").glob("*error*.log"))
access_re = re.compile(
    r'\[22/Oct/2026:(09|10):(\d{2}):(\d{2}) \+0000\] '
    r'"POST /api/documents/chat/ HTTP/[\d.]+" (\d{3}) (\d+)')
results = []
for p in paths:
    if not p.is_file() or p.is_symlink():
        continue
    with p.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 2000000))
        lines = f.read(2000001).decode("utf-8","replace").splitlines()
    for line in lines:
        m = access_re.search(line)
        if m:
            results.append(dict(UTC="{}:{}:{}".format(*m.groups()[:3]),
                                STATUS=m.group(4),
                                BODY_BYTES=int(m.group(5))))
reasons = {
    "UPSTREAM_READ_BODY_TIMEOUT": "upstream timed out",
    "UPSTREAM_CLOSED": "upstream prematurely closed",
    "CLIENT_ABORT": "client prematurely closed",
    "RESET": "connection reset by peer",
    "UPSTREAM_CONNECTION_FAILURE": "connect() failed",
}
counts = {k: 0 for k in reasons}
for p in errorpaths:
    if not p.is_file() or p.is_symlink():
        continue
    with p.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 2000000))
        lines = f.read(2000001).decode("utf-8","replace").splitlines()
    for line in lines:
        if not line.startswith(("2026/10/22 09:", "2026/10/22 10:")):
            continue
        if "/api/documents/chat/" not in line:
            continue
        low = line.lower()
        for key, pattern in reasons.items():
            if pattern in low:
                counts[key] += 1
print(json.dumps(dict(ACCESS=results[-20:],ERROR_COUNTS=counts),
                 sort_keys=True, separators=(",",":")))
'''


def run(args, timeout):
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        if r.returncode:
            return None
        return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    except (subprocess.TimeoutExpired, OSError):
        return None


def main():
    try:
        prox = run(["pct", "exec", "125", "--", "python3", "-c",
                    PROXY_INSPECT], timeout=25)
        if prox is None:
            print(FRAME + json.dumps({"STATUS":"PROXY_INSPECTION_FAILED"}))
            return
        proxy = json.loads(prox[0])
        if set(proxy) != {"ACCESS","ERROR_COUNTS"}:
            raise ValueError()
        logs = run(["pct", "exec", "126", "--", "podman", "logs",
                    "--timestamps", "--since", FROM_UTC,
                    "--until", TO_UTC, "bergen-paperless"], timeout=35)
        if logs is None:
            print(FRAME + json.dumps(dict(
                STATUS="PROXY_ONLY", ACCESS=proxy["ACCESS"],
                ERROR_COUNTS=proxy["ERROR_COUNTS"], BACKEND="NOT_READABLE"),
                sort_keys=True))
            return
        raw = logs[0] + "\n" + logs[1]
        patterns = {
            "CHAT_GENERATOR_ERROR": r"failed to stream document chat response",
            "MODEL_CONNECTION_ERROR": r"ollama.*(?:error|timeout|failed|unavailable)|(?:error|failed).*ollama",
            "REQUEST_TIMEOUT": r"readtimeout|timeoutexception|upstream.*timed out",
            "WORKER_TIMEOUT": r"worker timeout|worker was terminated",
            "BROKEN_PIPE": r"brokenpipeerror|broken pipe|connection reset by peer",
            "CHAT_ENDPOINT_500": r"POST /api/documents/chat/.* (?:500|502|503|504)\b",
        }
        counts = {name: len(re.findall(pat, raw, flags=re.I))
                  for name, pat in patterns.items()}
        print(FRAME + json.dumps(dict(
            STATUS="INSPECTED", ACCESS=proxy["ACCESS"],
            ERROR_COUNTS=proxy["ERROR_COUNTS"],
            BACKEND_ERROR_COUNTS=counts, CHANGED=False),
            sort_keys=True, separators=(",",":")))
    except Exception:
        print(FRAME + json.dumps({
            "STATUS":"UNCLASSIFIED","CHANGED":False}))


if __name__ == "__main__":
    main()
