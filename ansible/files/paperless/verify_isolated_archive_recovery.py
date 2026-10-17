#!/usr/bin/env python3
"""Controller-only volatile-memory copy test of a single NAS archive canary.

Pull an independently verified archived PDF from paperless-sync via SSH
without creating, moving, chmoding or deleting anything on Synology.
Place the copy in a mode 0700 temporary directory in /dev/shm (tmpfs),
verify streamed SHA-256, size and PDF structure, reopen and rehash,
then discard the copy. Nothing is printed from private SSH/PDF/journals.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ONLY = "Familie/Bergen-Platform-fuer-Dummies.pdf"
HOST_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*\Z")
STATE_RE = re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
LIMIT = 512 * 1024 * 1024
MAX_HEADER = 256


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def distinct_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_RECOVERY_HEADER")
        result[key] = value
    return result


def parse_header(line):
    """Strict protocol framing; never treat a remote error as PDF data."""
    require(type(line) is bytes and 0 < len(line) <= MAX_HEADER
            and line.endswith(b"\n"), "INVALID_RECOVERY_HEADER")
    doc = json.loads(line.decode("ascii"), object_pairs_hook=distinct_pairs)
    require(isinstance(doc, dict)
            and set(doc) == {"schema_version", "sha256", "bytes"}
            and type(doc["schema_version"]) is int
            and doc["schema_version"] == 1
            and type(doc["bytes"]) is int
            and 0 < doc["bytes"] <= LIMIT
            and isinstance(doc["sha256"], str)
            and HASH_RE.fullmatch(doc["sha256"]),
            "UNTRUSTED_RECOVERY_HEADER")
    return doc


def copy_stream(stream, scratch, header):
    """Copy exactly N bytes and verify all bytes; reject trailing output."""
    total = 0
    sha = hashlib.sha256()
    first, tail = b"", b""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    file_fd = os.open(scratch, flags, 0o600)
    with os.fdopen(file_fd, "wb") as target:
        while total < header["bytes"]:
            chunk = stream.read(min(1024 * 1024, header["bytes"] - total))
            require(chunk, "REMOTE_RECOVERY_TRUNCATED")
            target.write(chunk)
            sha.update(chunk)
            total += len(chunk)
            if not first:
                first = chunk[:8]
            tail = (tail + chunk)[-2048:]
        target.flush()
        os.fsync(target.fileno())
    require(stream.read(1) == b"", "REMOTE_RECOVERY_TRAILING_BYTES")
    require(total == header["bytes"]
            and sha.hexdigest() == header["sha256"]
            and first.startswith(b"%PDF-") and b"%%EOF" in tail,
            "REMOTE_RECOVERY_BYTES_INVALID")
    original_stat = scratch.lstat()
    require(stat.S_ISREG(original_stat.st_mode)
            and original_stat.st_nlink == 1
            and stat.S_IMODE(original_stat.st_mode) == 0o600
            and original_stat.st_size == total,
            "UNSAFE_RECOVERY_SCRATCH")
    local_sha = hashlib.sha256()
    with scratch.open("rb") as recovered:
        for block in iter(lambda: recovered.read(1024 * 1024), b""):
            local_sha.update(block)
    require(local_sha.hexdigest() == header["sha256"],
            "REOPENED_RECOVERY_SHA_MISMATCH")


def isolated_restore(host, parent, only, remote_code):
    require(isinstance(host, str) and HOST_RE.fullmatch(host)
            and isinstance(parent, str) and STATE_RE.fullmatch(parent)
            and only == ONLY and remote_code.is_file()
            and not remote_code.is_symlink(), "INVALID_RESTORE_REQUEST")
    script = remote_code.read_bytes()
    require(1000 < len(script) < 32768
            and b"READ_ONLY_NAS_RECOVERY_BLOCKED" in script,
            "UNTRUSTED_NAS_READONLY_SCRIPT")
    scratch_root = Path("/dev/shm")
    info = scratch_root.lstat()
    require(stat.S_ISDIR(info.st_mode)
            and not scratch_root.is_symlink()
            and os.access(scratch_root, os.W_OK | os.X_OK),
            "VOLATILE_TMPFS_UNAVAILABLE")
    # Require /dev/shm to be an actual tmpfs, not silently use disk.
    mounts = Path("/proc/mounts").read_text()
    require(any(row.split()[:3] == ["shm", "/dev/shm", "tmpfs"] or
                (len(row.split()) >= 3 and row.split()[1:3] ==
                 ["/dev/shm", "tmpfs"])
                for row in mounts.splitlines()),
            "VOLATILE_TMPFS_NOT_VERIFIED")
    remote_cmd = ("sudo -n -u paperless-sync /usr/bin/python3 - " +
                  shlex.quote(parent) + " " + shlex.quote(only))
    args = [
        "ssh", "-T", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15",
        host, remote_cmd,
    ]
    with tempfile.TemporaryDirectory(
            prefix="paperless-recovery-", dir=str(scratch_root)) as tmp:
        directory = Path(tmp)
        require(stat.S_IMODE(directory.lstat().st_mode) == 0o700,
                "UNSAFE_TMPFS_DIRECTORY")
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        try:
            # Source over SSH stdin; remote Python executes after EOF.
            proc.stdin.write(script)
            proc.stdin.close()
            header = parse_header(proc.stdout.readline(MAX_HEADER + 1))
            statvfs = os.statvfs(scratch_root)
            require(statvfs.f_bavail * statvfs.f_frsize >
                    header["bytes"] + 1024 * 1024,
                    "INSUFFICIENT_VOLATILE_SPACE")
            scratch = directory / "canary-recovered.pdf"
            copy_stream(proc.stdout, scratch, header)
            proc.stdout.close()
            status = proc.wait(timeout=180)
            remote_error = proc.stderr.read(4096)
            require(status == 0 and remote_error == b"",
                    "REMOTE_RECOVERY_SOURCE_CHECK_FAILED")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()
            proc.stderr.close()
            proc.stdin.close()
        # TemporaryDirectory now removes the verified copy and parent.
    print("ISOLATED_RECOVERY_COPY_REHASH_VERIFIED")
    print("VOLATILE_RECOVERY_COPY_REMOVED")
    print("NAS_RECOVERY_STREAM_READ_ONLY")
    print("NO_NAS_FILES_CHANGED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--state-parent", required=True)
    parser.add_argument("--only", required=True)
    parser.add_argument("--remote-script", type=Path, required=True)
    options = parser.parse_args()
    isolated_restore(options.ssh_host, options.state_parent,
                     options.only, options.remote_script)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("ISOLATED_RECOVERY_TEST_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
