#!/usr/bin/env python3
"""Read-only SSH local-forward diagnostic for NAS SMB/445.

No SMB authentication, no password, no protected-file operations.
Create temporary private controller-only control socket and SSH debug log,
use the minimal SMB3.0.2 NEGOTIATE program once, classify only allowlisted
SSH error types, and discard the local debug log without exposing content.
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import probe_synology_smb3_negotiate_wire as wire

REMOTE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]+\Z")


def classify_forwarding_log(raw, outcome):
    """Return fixed anonymous markers, never raw SSH log details."""
    content = raw.lower() if isinstance(raw, str) else ""
    if "administratively prohibited" in content:
        return "SSH_SERVER_TCP_FORWARD_DENIED"
    if "open failed: connect failed" in content:
        return "SSH_REMOTE_TARGET_CONNECT_FAILED"
    if "open failed" in content:
        return "SSH_CHANNEL_OPEN_FAILED_UNCLASSIFIED"
    if outcome == "SMB3_02_NEGOTIATED":
        return "SSH_FORWARD_SMB3_02_NEGOTIATED"
    if "direct-tcpip" in content and "connected to" in content:
        return "SSH_FORWARD_OPEN_SEEN_SMB_RESET"
    return "SSH_FORWARD_DIAGNOSTIC_INCONCLUSIVE"


def diagnose(remote):
    if not isinstance(remote, str) or not REMOTE.fullmatch(remote):
        raise RuntimeError("UNAPPROVED_SSH_ENDPOINT")
    with tempfile.TemporaryDirectory(prefix="paperless-ssh-forward-") as tmp:
        control = str(Path(tmp) / "control")
        logfile = Path(tmp) / "ssh-debug.log"
        cmd = [
            "ssh", "-fNTM", "-vv", "-E", str(logfile), "-S", control,
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ConnectTimeout=15",
            "-o", "ForwardAgent=no",
            "-o", "NumberOfPasswordPrompts=0",
            "-L", "127.0.0.1:1445:127.0.0.1:445",
            remote,
        ]
        started = None
        status = "NOT_TESTED"
        try:
            started = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=35)
            if started.returncode != 0:
                raise RuntimeError("SSH_LOCAL_FORWARD_SETUP_BLOCKED")
            status = wire.probe_one("127.0.0.1", 1445)
        finally:
            subprocess.run(
                ["ssh", "-S", control, "-O", "exit",
                 "-o", "BatchMode=yes", remote],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False, timeout=10)
        try:
            raw = logfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = ""
        verdict = classify_forwarding_log(raw, status)
    print("SSH_TUNNEL_SMB3_02_WIRE", status)
    print("SSH_TUNNEL_CHANNEL_VERDICT", verdict)
    print("SSH_DIAGNOSTIC_LOCAL_LOG_DISCARDED")
    print("NO_SMB_AUTHENTICATION_ATTEMPTED")
    print("NO_MUTATING_SMB_REQUESTS_SENT")
    print("NO_NAS_FILES_CHANGED")
    if status != "SMB3_02_NEGOTIATED":
        raise RuntimeError("SSH_FORWARD_SMB3_NOT_VERIFIED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh-host", required=True)
    args = parser.parse_args()
    diagnose(args.ssh_host)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("SSH_SMB_FORWARD_DIAGNOSTIC_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
