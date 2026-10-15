#!/usr/bin/env python3
"""Staged v2 process preflight: read-only SSH receiver, rsync argv plan.

NO CLI, NO NAS deployment, NO sender wiring, NO SENT/ARCHIVE/DELETE.
The receiver action *can* perform a read-only remote SSH check if explicitly
called in Python by a privileged operator; tests patch subprocess.run.
The rsync plan is NEVER executed by this module. The future sender requires
a durable ATTEMPTED event before any real rsync subprocess may start.
"""
import hashlib
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

from compare_v2_transfer_evidence_offline import _receiver_success, _source_prepared

SSH_TARGET = re.compile(r"[a-z_][a-z0-9_.-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z")
MAX_PDF = 512 * 1024 * 1024
MAX_SCRIPT = 16000


def _file(path, allowed_modes, maximum=None):
    if (not isinstance(path, Path) or not path.is_absolute()
            or ".." in path.parts or path == Path("/")):
        raise ValueError("ABSOLUTE_TRUSTED_FILE_REQUIRED")
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(before.st_mode) not in allowed_modes
            or (maximum is not None and not 0 < before.st_size <= maximum)):
        raise RuntimeError("UNSAFE_TRUSTED_FILE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_mode, before.st_uid,
            before.st_size, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid,
            after.st_size, after.st_ctime_ns):
            raise RuntimeError("TRUSTED_FILE_CHANGED")
        if maximum is None:
            return None
        raw = os.read(fd, maximum + 1)
        if len(raw) != before.st_size:
            raise RuntimeError("TRUSTED_FILE_CHANGED")
        after = os.fstat(fd)
        if (after.st_size, after.st_ctime_ns, after.st_mtime_ns) != (
            before.st_size, before.st_ctime_ns, before.st_mtime_ns):
            raise RuntimeError("TRUSTED_FILE_CHANGED")
        return raw
    finally:
        os.close(fd)


def _ssh_parts(target, identity, known_hosts):
    if type(target) is not str or not SSH_TARGET.fullmatch(target):
        raise ValueError("INVALID_PINNED_SSH_TARGET")
    if not isinstance(identity, Path) or not isinstance(known_hosts, Path):
        raise ValueError("SSH_PATHS_MUST_BE_PATHS")
    _file(identity, (0o400, 0o600), 16384)
    _file(known_hosts, (0o400, 0o600, 0o644), 131072)
    return [
        "ssh", "-T", "-i", str(identity),
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=" + str(known_hosts),
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=15",
        "-o", "ConnectionAttempts=1",
        target,
    ]


def _expected(prepared):
    return _source_prepared(prepared)


def build_rsync_plan(prepared, snapshot, destination, identity, known_hosts):
    """Pure *argv planner*, not an rsync execution or retry authorization.

    Prepared is nonce-bound. Snapshot must already be safely frozen/renamed
    to the exact receiver basename. Never execute this plan without a durable
    ATTEMPTED marker and a reviewed remote rsync restriction.
    """
    item = _expected(prepared)
    if (not isinstance(snapshot, Path) or not snapshot.is_absolute()
            or ".." in snapshot.parts
            or snapshot.name != item["destination"].rsplit("/", 1)[1]):
        raise ValueError("SNAPSHOT_NAME_NOT_BOUND_TO_RECEIPT")
    _file(snapshot, (0o600,))
    source_fd = os.open(snapshot, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(source_fd)
        if not 0 < before.st_size <= MAX_PDF:
            raise RuntimeError("INVALID_SNAPSHOT_SIZE")
        sha = hashlib.sha256()
        with os.fdopen(source_fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(block)
        after = os.fstat(source_fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns,
            before.st_ino) != (after.st_size, after.st_mtime_ns,
            after.st_ctime_ns, after.st_ino):
            raise RuntimeError("SNAPSHOT_CHANGED_DURING_PLAN")
        if before.st_size != item["signature"][2] or sha.hexdigest() != item["sha256"]:
            raise RuntimeError("SNAPSHOT_NOT_BOUND_TO_RECEIPT")
    finally:
        os.close(source_fd)
    ssh = _ssh_parts(destination, identity, known_hosts)
    # rsync -e takes one token containing the entire transport command.
    # Every component is generated, quoted, and contains no shell input.
    return (
        "rsync", "-av", "--ignore-existing", "--chmod=F600",
        "--out-format=%i %n", "-e", shlex.join(ssh[:-1]),
        "--", str(snapshot), destination + ":" + item["scope"] + "/",
    )


def _run_ssh(ssh, remote_tokens, script=None):
    # Remote OpenSSH ultimately invokes a login shell: shlex.quote every token.
    argv = [*ssh, shlex.join(remote_tokens)]
    result = subprocess.run(
        argv, input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=45, check=False, shell=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
    )
    if (type(result.returncode) is not int or result.returncode != 0
            or not isinstance(result.stdout, bytes)
            or not isinstance(result.stderr, bytes)
            or result.stderr
            or len(result.stdout) > 16384):
        raise RuntimeError("REMOTE_PCT_AUDIT_FAILED")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeError as exc:
        raise RuntimeError("REMOTE_PCT_AUDIT_ENCODING") from exc


def run_readonly_receiver(prepared, venombox_target, identity, known_hosts):
    """Execute the RECEIVER CHECK from a controller, never send a PDF.

    This action is not a production trust/completion gate until exact SSH
    account, sudo privileges, pinned host key and LXC identity are verified
    in the target deployment. It never creates receipts or grants SENT.
    """
    item = _expected(prepared)
    ssh = _ssh_parts(venombox_target, identity, known_hosts)
    base = ["sudo", "-n", "/usr/sbin/pct"]
    cfg = _run_ssh(ssh, [*base, "config", "126"])
    if ("hostname: bergen-paperless" not in cfg.splitlines()
            or "unprivileged: 1" not in cfg.splitlines()
            or "lxc.apparmor.profile: unconfined" in cfg):
        raise RuntimeError("WRONG_OR_UNSAFE_RECEIVER_GUEST")
    status = _run_ssh(ssh, [*base, "status", "126"])
    if status.strip() != "status: running":
        raise RuntimeError("RECEIVER_GUEST_NOT_RUNNING")
    script = Path(__file__).with_name("verify_receiver_v2_staging.py")
    program = _file(script, (0o444, 0o644, 0o600), MAX_SCRIPT)
    scope, filename = item["destination"].rsplit("/", 1)
    command = [
        *base, "exec", "126", "--", "/usr/sbin/runuser", "-u",
        "paperless-ingest", "--", "/usr/bin/python3", "-",
        scope, filename, item["sha256"], str(item["signature"][2]),
    ]
    output = _run_ssh(ssh, command, script=program)
    _receiver_success(output, item)
    return {
        "receiver_source": item["destination"],
        "receiver_sha256": item["sha256"],
        "receiver_bytes": item["signature"][2],
        "receiver_process_checked": True,
        "ssh_strict_hostkey_enforced": True,
        "sender_attempt_authenticated": False,
        "sent_authorized": False,
        "source_delete_authorized": False,
    }


__all__ = ["build_rsync_plan", "run_readonly_receiver"]
