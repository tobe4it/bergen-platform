#!/usr/bin/env python3
"""ProxyCommand transport: controller -> Proxmox SSH -> pct exec -> guest sshd.

No guest networking route, host routing change, third-party package, or firewall
exception required. The guest must have Python 3 and a running SSH service.

Usage:
    ssh -o 'ProxyCommand=python3 ansible/scripts/pct_ssh_proxy.py \
        --pve-host PROXMOX_HOST --vmid VMID' -o HostKeyAlias=lxc-VMID \
        root@GUEST_IP hostname

The inner SSH validates the trusted Proxmox host key; the outer SSH validates
the guest's SSH host key independently. Never disable either check.
"""
import argparse
import os
import re
import shlex
import sys

# Runs only inside the specifically selected guest, not on the PVE host.
# A reader thread permits full-duplex byte-oriented SSH traffic over stdio.
GUEST_RELAY = r'''
import socket
import sys
import threading

sock = socket.create_connection(("127.0.0.1", 22), timeout=10)
sock.settimeout(None)

def stdin_to_socket():
    try:
        while True:
            data = sys.stdin.buffer.read1(65536)
            if not data:
                break
            sock.sendall(data)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

threading.Thread(target=stdin_to_socket, daemon=True).start()
try:
    while True:
        data = sock.recv(65536)
        if not data:
            break
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
finally:
    sock.close()
'''


def build_command(host: str, vmid: int, user: str = "root") -> list[str]:
    """Build a constant-shape, injection-resistant command for execvp."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}", host):
        raise ValueError("Invalid PVE host; use an IP or DNS hostname")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        raise ValueError("Invalid PVE SSH username")
    if vmid < 100 or vmid > 999999999:
        raise ValueError("VMID is outside Proxmox guest ID range")

    guest_command = (
        f"pct exec {vmid} -- /usr/bin/python3 -c "
        f"{shlex.quote(GUEST_RELAY)}"
    )
    return [
        "ssh", "-T",
        "-o", "BatchMode=yes",
        "-o", "ClearAllForwardings=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "LogLevel=ERROR",
        "--", f"{user}@{host}", guest_command,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pve-host", required=True,
                        help="Reachable Proxmox SSH IP/hostname")
    parser.add_argument("--vmid", type=int, required=True,
                        help="Existing Proxmox LXC VMID")
    parser.add_argument("--pve-user", default="root",
                        help="Authorized Proxmox SSH user, default root")
    args = parser.parse_args()
    try:
        cmd = build_command(args.pve_host, args.vmid, args.pve_user)
    except ValueError as exc:
        parser.error(str(exc))

    # Important: ProxyCommand owns stdin/stdout directly. Do not log to stdout.
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
