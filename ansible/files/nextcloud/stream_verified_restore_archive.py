#!/usr/bin/env python3
"""Stream one fixed verified mx2 Nextcloud archive to venombox via two SSH links.

No password handling, SSH agent forwarding, NFS writes, guest startup or
insecure host key acceptance. Run only from the approved controller.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

SNAPSHOT_RE = re.compile(r"20\d{6}T\d{6}Z-\d+\Z")
SOURCE_SCRIPT = r'''
import hashlib, json, os, re, socket, stat, subprocess, sys
from pathlib import Path
mode, ident, expected_export = sys.argv[1:]
if socket.getfqdn() != "mx.thebergens.net":
    raise SystemExit(71)
if not re.fullmatch(r"20\d{6}T\d{6}Z-\d+", ident):
    raise SystemExit(72)
mount = Path("/mnt/nextcloud-backup")
check = subprocess.run(["findmnt","-rn","-o","SOURCE","-M",str(mount)],
    capture_output=True, check=False, text=True)
if check.returncode or check.stdout.strip() != expected_export:
    raise SystemExit(73)
base = mount / "mx2-nextcloud"
directory = base / ("backup-" + ident)
if not base.is_dir() or base.is_symlink() or directory.is_symlink() or not directory.is_dir():
    raise SystemExit(74)
archive = directory / "nextcloud.tar.gz"
if archive.is_symlink() or not archive.is_file():
    raise SystemExit(75)
digest_file = directory / "SHA256SUMS"
complete_file = directory / "COMPLETE"
if digest_file.is_symlink() or complete_file.is_symlink():
    raise SystemExit(76)
sums = digest_file.read_text().strip().split("  ")
if len(sums) != 2 or sums[1] != "nextcloud.tar.gz" or not re.fullmatch("[0-9a-f]{64}", sums[0]):
    raise SystemExit(77)
digest = sums[0]
if complete_file.read_text().strip() != "VERIFIED_SHA256=" + digest:
    raise SystemExit(78)
fd = os.open(archive, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
try:
    size = os.fstat(fd).st_size
    if size < 1024 * 1024 or not stat.S_ISREG(os.fstat(fd).st_mode):
        raise SystemExit(79)
    if mode == "metadata":
        print(json.dumps({"bytes":size, "digest":digest, "snapshot_id":ident}))
    elif mode == "stream":
        out = sys.stdout.buffer
        while True:
            b = os.read(fd, 4 * 1024 * 1024)
            if not b:
                break
            out.write(b)
        out.flush()
    else:
        raise SystemExit(80)
finally:
    os.close(fd)
'''
DEST_SCRIPT = r'''
import hashlib, json, os, re, socket, stat, subprocess, sys
from pathlib import Path
mode, ident, expected_size, expected_digest = sys.argv[1:]
if socket.gethostname().split(".")[0] != "venombox":
    raise SystemExit(71)
if not re.fullmatch(r"20\d{6}T\d{6}Z-\d+", ident):
    raise SystemExit(72)
size = int(expected_size)
if not (1024*1024 < size < 60*1024**3) or not re.fullmatch("[0-9a-f]{64}", expected_digest):
    raise SystemExit(73)
root = Path("/var/lib/vz/nextcloud-restore-test")
if root.is_symlink() or not root.is_dir():
    raise SystemExit(74)
st = root.stat()
if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
    raise SystemExit(75)
conf = subprocess.run(["pct","config","701"],capture_output=True,text=True,check=False)
status = subprocess.run(["pct","status","701"],capture_output=True,text=True,check=False)
cfg = conf.stdout.splitlines()
checks = ["hostname: nextcloud-restore-701","unprivileged: 1","onboot: 0","protection: 1"]
if conf.returncode or status.returncode or "status: stopped" not in status.stdout or not all(c in cfg for c in checks):
    raise SystemExit(76)
if any(re.match(r"net\d+:", c) for c in cfg):
    raise SystemExit(77)
name = "nextcloud-" + ident + ".tar.gz"
out = root / name
part = root / (".incoming-" + ident + ".part")
if out.exists() or out.is_symlink() or part.exists() or part.is_symlink():
    raise SystemExit(78)
if mode == "probe":
    print("DESTINATION_PROBE_READY")
    raise SystemExit(0)
if mode != "receive":
    raise SystemExit(79)
fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,"O_NOFOLLOW",0), 0o600)
success = False
try:
    hasher = hashlib.sha256()
    transferred = 0
    while True:
        chunk = sys.stdin.buffer.read(4*1024*1024)
        if not chunk:
            break
        transferred += len(chunk)
        if transferred > size:
            raise SystemExit(80)
        hasher.update(chunk)
        view = memoryview(chunk)
        while view:
            n = os.write(fd, view)
            view = view[n:]
    os.fsync(fd)
    if transferred != size or hasher.hexdigest() != expected_digest:
        raise SystemExit(81)
    os.link(part, out, follow_symlinks=False)
    os.unlink(part)
    success = True
    dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    print("NEXTCLOUD_RESTORE_ARCHIVE_STAGED_AND_SHA256_VERIFIED=YES")
finally:
    os.close(fd)
    if not success:
        try: os.unlink(part)
        except FileNotFoundError: pass
'''

def ssh_command(host, user, port, script, *args):
    # Host keys must already be trusted by the existing Ansible controller.
    # All remote script arguments are individually shell-quoted.
    remote_python = "/usr/bin/python3"
    command = ([remote_python] if user == "root" else
               ["sudo", "-n", remote_python])
    command += ["-c", script, *args]
    return [
        "ssh", "-T", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "ForwardAgent=no",
        "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=6", "-o", "NumberOfPasswordPrompts=0",
        "-p", str(port), "-l", user, host, shlex.join(command)
    ]

def do_run(command):
    return subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=60, check=False
    )

def fail(msg):
    print("NEXTCLOUD_RESTORE_TRANSFER_FAILED=" + msg, file=sys.stderr)
    raise SystemExit(2)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--source-user", required=True)
    p.add_argument("--source-port", type=int, default=22)
    p.add_argument("--target", required=True)
    p.add_argument("--target-user", required=True)
    p.add_argument("--target-port", type=int, default=22)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--export", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if not SNAPSHOT_RE.fullmatch(args.snapshot):
        fail("UNAPPROVED_SNAPSHOT_ID")
    for host in (args.source, args.target):
        if not host or any(c.isspace() for c in host) or host.startswith("-"):
            fail("UNSAFE_SSH_TARGET")
    for user in (args.source_user, args.target_user):
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
            fail("UNSAFE_SSH_USERNAME")
    if not all(1 <= x <= 65535 for x in (args.source_port, args.target_port)):
        fail("UNSAFE_SSH_PORT")
    if not re.fullmatch(r"[0-9.]+:/[A-Za-z0-9/._-]+", args.export):
        fail("UNAPPROVED_EXPORT")
    if args.source == args.target:
        fail("SOURCE_EQUALS_DESTINATION")
    src = lambda mode: ssh_command(
        args.source, args.source_user, args.source_port, SOURCE_SCRIPT,
        mode, args.snapshot, args.export
    )
    result = do_run(src("metadata"))
    if result.returncode:
        fail("SOURCE_SSH_OR_SOURCE_METADATA_UNAVAILABLE")
    if len(result.stdout) > 1024:
        fail("OVERSIZED_METADATA")
    try:
        metadata = json.loads(result.stdout)
        size = int(metadata["bytes"])
        digest = metadata["digest"]
        if metadata["snapshot_id"] != args.snapshot:
            raise ValueError("snapshot mismatch")
        if not (1024*1024 < size < 60*1024**3):
            raise ValueError("invalid size")
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("invalid hash")
    except (ValueError, KeyError, TypeError):
        fail("INVALID_SOURCE_METADATA")

    dst = lambda mode: ssh_command(
        args.target, args.target_user, args.target_port, DEST_SCRIPT,
        mode, args.snapshot, str(size), digest
    )
    probe = do_run(dst("probe"))
    if probe.returncode or probe.stdout.strip() != b"DESTINATION_PROBE_READY":
        fail("DESTINATION_SSH_OR_BOUNDARY_UNAVAILABLE")
    print("NEXTCLOUD_RESTORE_SSH_BOTH_ENDPOINTS_VERIFIED=YES")
    print("SNAPSHOT_ID=" + args.snapshot)
    print("ARCHIVE_BYTES=" + str(size))
    if not args.apply:
        print("NEXTCLOUD_RESTORE_TRANSFER_READ_ONLY_READY")
        return

    source = subprocess.Popen(src("stream"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    target = subprocess.Popen(dst("receive"), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    controller_digest = hashlib.sha256()
    sent = 0
    try:
        while True:
            block = source.stdout.read(4 * 1024 * 1024)
            if not block:
                break
            sent += len(block)
            if sent > size:
                fail("SOURCE_STREAM_TOO_LARGE")
            controller_digest.update(block)
            target.stdin.write(block)
        target.stdin.close()
        source.stdout.close()
        src_rc = source.wait(timeout=60)
        receipt = target.stdout.read(2048)
        dst_rc = target.wait(timeout=60)
        if src_rc or dst_rc:
            fail("SSH_TRANSFER_OR_DESTINATION_FAILED")
        if sent != size or controller_digest.hexdigest() != digest:
            fail("CONTROLLER_STREAM_HASH_MISMATCH")
        if receipt.strip() != b"NEXTCLOUD_RESTORE_ARCHIVE_STAGED_AND_SHA256_VERIFIED=YES":
            fail("TARGET_RECEIPT_INVALID")
        print("NEXTCLOUD_RESTORE_ARCHIVE_TRANSFER_COMPLETE=YES")
    finally:
        if source.poll() is None:
            source.kill()
        if target.poll() is None:
            target.kill()

if __name__ == "__main__":
    main()
