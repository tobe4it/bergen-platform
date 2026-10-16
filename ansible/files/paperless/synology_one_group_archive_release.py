#!/usr/bin/env python3
"""Explicit operator one-PDF release runner; root wrapper, only for GROUP SCOPES.

This root-owned code is invoked by a controller play that just performed full
live NAS/Paperless lifecycle verification. It installs a short-lived canonical
EXACT-PDF release gate, executes the already installed reviewed worker as
paperless-sync, and removes that gate in finally. No bulk/site-wide gate or
deletion worker, no document or receipt modification apart from authorized
single original relocation and its required durable archive journal.

NEVER expose stdout/stderr from the underlying worker: those contain receipt IDs.
An ambiguous crash between PREPARED/rename/ARCHIVED requires manual recovery
and blocks later moves. The gate is time-limited even after abrupt termination.
"""
import argparse
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

SCOPES = frozenset(("Eltern", "Familie"))
GATE = "archive-move.paperless-scan.enabled"
OTHERS = ("archive-move.enabled", "archive-move.homes.enabled", GATE)
SEND = re.compile(r"[0-9a-f]{64}[.]json\Z")
BRIDGE = re.compile(r"[0-9a-f]{24}[.]json\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_INPUT = 16384


def demand(yes, why):
    if not yes:
        raise RuntimeError(why)


def unique(pairs):
    result = {}
    for k, v in pairs:
        demand(k not in result, "DUPLICATE_PRIVATE_PROOF_FIELD")
        result[k] = v
    return result


def safe_file(path, uid, mode, gid=None):
    before = path.lstat()
    demand(stat.S_ISREG(before.st_mode) and before.st_uid == uid and
           before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == mode and
           (gid is None or before.st_gid == gid), "UNTRUSTED_ARCHIVE_CODE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        after = os.fstat(fd)
        demand((after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                after.st_gid, after.st_nlink) ==
               (before.st_dev, before.st_ino, before.st_mode, before.st_uid,
                before.st_gid, before.st_nlink), "ARCHIVE_CODE_RACED")
    finally:
        os.close(fd)


def verify_dir(path, uid, mode):
    first = path.lstat()
    demand(stat.S_ISDIR(first.st_mode) and first.st_uid == uid and
           stat.S_IMODE(first.st_mode) == mode, "UNSAFE_RELEASE_PARENT")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY |
                 os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        now = os.fstat(fd)
        demand((first.st_ino, first.st_dev, first.st_mode,
                first.st_uid) ==
               (now.st_ino, now.st_dev, now.st_mode, now.st_uid),
               "RELEASE_PARENT_CHANGED")
    finally:
        os.close(fd)


def manifest(only, proof, now):
    scope, sep, source = only.rpartition("/")
    demand(sep and scope in SCOPES and source and
           source not in (".", "..") and not source.startswith(".") and
           "/" not in source and "\\" not in source and "\x00" not in source and
           source.lower().endswith(".pdf") and
           len(source.encode("utf-8")) <= 255, "INVALID_GROUP_OR_SOURCE")
    demand(isinstance(proof, dict) and set(proof) == {
        "schema_version", "sender_receipt", "bridge_receipt",
        "receiver_source", "sha256", "document_id",
    }, "INVALID_FRESH_IMPORT_PROOF")
    sha = proof["sha256"]
    demand(type(proof["schema_version"]) is int and
           proof["schema_version"] == 1 and
           isinstance(sha, str) and SHA.fullmatch(sha) and
           isinstance(proof["sender_receipt"], str) and
           SEND.fullmatch(proof["sender_receipt"]) and
           isinstance(proof["bridge_receipt"], str) and
           BRIDGE.fullmatch(proof["bridge_receipt"]) and
           type(proof["document_id"]) is int and
           proof["document_id"] > 0 and
           isinstance(proof["receiver_source"], str) and
           proof["receiver_source"].startswith(scope + "/") and
           proof["receiver_source"].endswith("--nas-" + sha + ".pdf") and
           proof["sender_receipt"] == hashlib.sha256(
               (scope + "\0" + source).encode("utf-8")).hexdigest() + ".json",
           "GROUP_RELEASE_PROOF_IDENTITY_MISMATCH")
    demand(type(now) is int and now > 0, "INVALID_RELEASE_CLOCK")
    result = {
        "schema_version": 1,
        "release": "one_original_pdf",
        "site": "paperless-scan",
        "scope": scope,
        "source": source,
        "sender_receipt": proof["sender_receipt"],
        "bridge_receipt": proof["bridge_receipt"],
        "sha256": sha,
        "document_id": proof["document_id"],
        "issued_at": now,
        "expires_at": now + 600,
    }
    return (json.dumps(result, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def execute(parent, only, proof, *, call=None, now=None):
    demand(os.geteuid() == 0 and parent.is_absolute() and
           parent != Path("/") and ".." not in parent.parts and
           re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(parent)),
           "ROOT_AND_EXACT_STATE_PARENT_REQUIRED")
    verify_dir(parent, 0, 0o755)
    bindir = parent / "bin"
    verify_dir(bindir, 0, 0o755)
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    demand(SETTINGS["parent"] == parent and
           SETTINGS["sync_user"] == "paperless-sync" and
           len(SETTINGS["sources"]) == 4, "RELEASE_SITE_CONFIGURATION_CHANGED")
    user = pwd.getpwnam(SETTINGS["sync_user"])
    demand(user.pw_uid != 0, "RELEASE_MUST_DROP_ROOT")
    worker = bindir / "synology_same_volume_archive_move.py"
    safe_file(worker, 0, 0o644, 0)
    for name in OTHERS:
        path = parent / name
        demand(not path.exists() and not path.is_symlink(),
               "ANOTHER_ARCHIVE_GATE_PRESENT")
    issued = int(time.time()) if now is None else now
    raw = manifest(only, proof, issued)
    gate = parent / GATE
    fd = -1
    created = None
    dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY |
                     os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        # Exclusive root-only fixed gate. Never overwrite preexisting flags.
        fd = os.open(GATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        created = os.fstat(fd)
        demand(created.st_uid == 0 and created.st_gid == 0 and
               stat.S_IMODE(created.st_mode) == 0o600 and
               created.st_nlink == 1, "INVALID_CREATED_GATE")
        demand(os.write(fd, raw) == len(raw), "ARCHIVE_GATE_SHORT_WRITE")
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.fsync(dir_fd)

        def drop():
            os.initgroups(user.pw_name, user.pw_gid)
            os.setgid(user.pw_gid)
            os.setuid(user.pw_uid)

        subprocess_run = call or subprocess.run
        # The private proof is passed by stdin, never by argv or logs.
        result = subprocess_run(
            ["/usr/bin/python3", str(worker), "--state-parent",
             str(parent), "--only", only, "--commit"],
            input=json.dumps(proof, separators=(",", ":"), ensure_ascii=True),
            capture_output=True, text=True, check=False, timeout=480,
            preexec_fn=drop, env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "PYTHONNOUSERSITE": "1",
            },
        )
        demand(result.returncode == 0 and not result.stderr,
               "ARCHIVE_WORKER_COMMIT_FAILED")
        lines = result.stdout.splitlines()
        month = r"20[0-9]{2}-(0[1-9]|1[0-2])"
        expected = ("ARCHIVE_MOVED " + proof["sender_receipt"] + " ")
        demand(len(lines) == 2 and lines[0].startswith(expected) and
               re.fullmatch(month + r" " + proof["sender_receipt"][:-5] + "[.]pdf",
                            lines[0][len(expected):]) and
               lines[1] == "ARCHIVE_PURGE_DISABLED",
               "UNEXPECTED_ARCHIVE_WORKER_RESULT")
    finally:
        if fd >= 0:
            os.close(fd)
        if created is not None:
            # Never unlink a substituted gate. A mismatch is a BLOCKER.
            current = os.stat(GATE, dir_fd=dir_fd, follow_symlinks=False)
            demand((current.st_ino, current.st_dev, current.st_uid,
                    current.st_gid, current.st_mode) ==
                   (created.st_ino, created.st_dev, created.st_uid,
                    created.st_gid, created.st_mode),
                   "ROOT_ARCHIVE_GATE_REPLACED")
            os.unlink(GATE, dir_fd=dir_fd)
            os.fsync(dir_fd)
        os.close(dir_fd)
    print("ONE_GROUP_PDF_ARCHIVE_MOVED")
    print("EXACT_RELEASE_GATE_REVOKED")
    print("ARCHIVE_PURGE_DISABLED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-parent", required=True)
    parser.add_argument("--only", required=True)
    args = parser.parse_args()
    payload = sys.stdin.buffer.read(MAX_INPUT + 1)
    demand(0 < len(payload) <= MAX_INPUT, "PRIVATE_PROOF_SIZE_INVALID")
    proof = json.loads(payload, object_pairs_hook=unique)
    execute(Path(args.state_parent), args.only, proof)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, TypeError, ValueError, KeyError,
            subprocess.TimeoutExpired, subprocess.SubprocessError):
        # No private filenames, user principals, receipt IDs, or hashes.
        print("ONE_GROUP_PDF_ARCHIVE_BLOCKED", file=sys.stderr)
        sys.exit(1)
