#!/usr/bin/env python3
"""Conservative same-subvolume NAS archive move, MANUAL/OPT-IN only.

One explicitly selected v1 SENT source, only after live Paperless import proof.
No cleanup/purge. Dry-run by default. No scheduled entry point or deployment.
No-overwrite Linux renameat2, immutable journal before and after. On any
ambiguous crash STOP: manual reconciliation is required.

The proof must be freshly gathered through the separately reviewed controller
audit (NAS + LXC 126) and handed to this command over a trusted SSH session.
This script verifies proof identity, but CANNOT authenticate its live origin.
Do not activate production commit before independent ACL/backup/writer tests.
"""
import argparse
import ctypes
import datetime
import errno
import hashlib
import json
import os
import pwd
import re
import stat
import sys
import time
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

SCOPES = frozenset(("Familie", "Eltern", "Privat/thomas", "Privat/nadja"))
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
BRIDGE = re.compile(r"[a-f0-9]{24}\.json\Z")
# Never use old per-source .paperless-archive directories: scanner users can
# delete or rename their entries via parent DSM ACL delete-child privileges.
PROTECTED_ARCHIVE_DIR = ".bergen-paperless-archive"
SITE_BY_SCOPE = {
    "Familie": "paperless-scan",
    "Eltern": "paperless-scan",
    "Privat/thomas": "homes",
    "Privat/nadja": "homes",
}
JOURNAL_DIR = "archive-move-journal"
MAX_BYTES = 512 * 1024 * 1024
RENAME_NOREPLACE = 1


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def source_signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _check_dir(path, owner, mode=0o700):
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == owner
            and stat.S_IMODE(st.st_mode) == mode, "UNSAFE_ARCHIVE_DIRECTORY")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        current = os.fstat(fd)
        require((st.st_dev, st.st_ino, st.st_mode, st.st_uid) ==
                (current.st_dev, current.st_ino, current.st_mode, current.st_uid),
                "ARCHIVE_DIRECTORY_RACED")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _fsync_dir(fd):
    os.fsync(fd)


def _validated_protected_scope(source_dir, scope, sync_uid):
    """Resolve archive path from configured source mount, not user input.

    The topmost same-device ancestor must be the expected Synology site
    ("homes" or "paperless-scan"), owned by root. Reject symlink ancestors,
    wrong devices, and any missing / improperly secured protected scope.
    A separate live native DSM ACL audit remains mandatory before commits.
    """
    require(scope in SITE_BY_SCOPE and isinstance(source_dir, Path)
            and source_dir.is_absolute() and ".." not in source_dir.parts,
            "INVALID_ARCHIVE_SCOPE_OR_SOURCE")
    expected_site = SITE_BY_SCOPE[scope]
    info = source_dir.lstat()
    require(stat.S_ISDIR(info.st_mode), "UNSAFE_SOURCE_DIR")
    current = source_dir
    for _ in range(32):
        require(current.parent != current, "ARCHIVE_DEVICE_BOUNDARY_NOT_FOUND")
        parent = current.parent
        pinfo = parent.lstat()
        require(stat.S_ISDIR(pinfo.st_mode), "UNSAFE_ARCHIVE_PATH_ANCESTOR")
        if pinfo.st_dev != info.st_dev:
            break
        current = parent
    else:
        raise RuntimeError("ARCHIVE_DEVICE_BOUNDARY_TOO_DEEP")
    root_info = current.lstat()
    require(current.name == expected_site and stat.S_ISDIR(root_info.st_mode)
            and root_info.st_uid == 0 and root_info.st_dev == info.st_dev,
            "ARCHIVE_SITE_ROOT_MISMATCH")
    archive_root = current / PROTECTED_ARCHIVE_DIR
    paths = [archive_root]
    for part in scope.split("/"):
        paths.append(paths[-1] / part)
    for path in paths:
        fd = _check_dir(path, sync_uid)
        try:
            require(os.fstat(fd).st_dev == info.st_dev,
                    "PROTECTED_ARCHIVE_DEVICE_MISMATCH")
        finally:
            os.close(fd)
    return paths[-1]


def _validate_archive_scope_path(archive_scope_dir, source_dir, scope):
    """Reject the obsolete scanner-writable archive path even in dry-run."""
    require(isinstance(archive_scope_dir, Path) and archive_scope_dir.is_absolute()
            and ".." not in archive_scope_dir.parts,
            "INVALID_PROTECTED_ARCHIVE_PATH")
    parts = (PROTECTED_ARCHIVE_DIR, *scope.split("/"))
    require(tuple(archive_scope_dir.parts[-len(parts):]) == parts
            and source_dir not in archive_scope_dir.parents
            and archive_scope_dir != source_dir,
            "ARCHIVE_NOT_IN_PROTECTED_SITE")


def _require_site_commit_gate(state_parent, site):
    """Only a per-site root-owned 0600 release authorizes live rename.

    Never accept the former archive-move.enabled global flag. No gate is
    generated in the repository or deployed by archive worker staging.
    """
    require(site in frozenset(SITE_BY_SCOPE.values()), "INVALID_ARCHIVE_SITE")
    legacy = state_parent / "archive-move.enabled"
    require(not legacy.exists() and not legacy.is_symlink(),
            "LEGACY_ARCHIVE_GATE_MUST_BE_ABSENT")
    gate = state_parent / ("archive-move." + site + ".enabled")
    try:
        st = gate.lstat()
    except FileNotFoundError:
        raise RuntimeError("ARCHIVE_SITE_GATE_NOT_APPROVED") from None
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_nlink == 1
            and stat.S_IMODE(st.st_mode) == 0o600,
            "ARCHIVE_SITE_GATE_NOT_APPROVED")


def _read_source(dirfd, name, limit, *, expected_signature, expected_sha,
                 after_rename=False):
    before = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    def identity_ok(st):
        signature = source_signature(st)
        return (signature[:4] == expected_signature[:4]
                and (not after_rename and signature[4] == expected_signature[4]
                     or after_rename and signature[4] >= expected_signature[4]))
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and 0 < before.st_size <= min(limit, MAX_BYTES)
            and identity_ok(before),
            "SOURCE_IDENTITY_MISMATCH")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                 dir_fd=dirfd)
    try:
        require(source_signature(os.fstat(fd)) == source_signature(before),
                "SOURCE_CHANGED_DURING_OPEN")
        sha = hashlib.sha256()
        head, tail = b"", b""
        with os.fdopen(fd, "rb", closefd=False) as data:
            for block in iter(lambda: data.read(1024 * 1024), b""):
                if not head:
                    head = block[:8]
                tail = (tail + block)[-2048:]
                sha.update(block)
        require(source_signature(os.fstat(fd)) == source_signature(before) and
                source_signature(os.stat(name, dir_fd=dirfd,
                                         follow_symlinks=False)) == source_signature(before),
                "SOURCE_CHANGED_DURING_READ")
        require(head.startswith(b"%PDF-") and b"%%EOF" in tail,
                "SOURCE_NOT_PDF")
        require(sha.hexdigest() == expected_sha, "SOURCE_SHA_MISMATCH")
    finally:
        os.close(fd)


def _fsync_existing_pdf(dirfd, name, expected_signature):
    """Persist existing PDF file data before/after the metadata-only rename."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                 dir_fd=dirfd)
    try:
        require(source_signature(os.fstat(fd))[:4] == expected_signature[:4],
                "PDF_CHANGED_BEFORE_FSYNC")
        os.fsync(fd)
        after = os.fstat(fd)
        require(source_signature(after)[:4] == expected_signature[:4],
                "PDF_CHANGED_AFTER_FSYNC")
    finally:
        os.close(fd)


def _read_receipt(path, scope, source, signature, expected_sha):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == os.geteuid()
            and stat.S_IMODE(before.st_mode) == 0o600
            and 0 < before.st_size <= 4096, "UNSAFE_SENDER_RECEIPT")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(os.fstat(fd).st_ino == before.st_ino, "SENDER_RECEIPT_CHANGED")
        with os.fdopen(fd, "rb", closefd=False) as f:
            raw = f.read(4097)
    finally:
        os.close(fd)
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("DUPLICATE_RECEIPT_KEY")
            obj[k] = v
        return obj
    record = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(record, dict) and record.get("status") == "SENT"
            and record.get("scope") == scope and record.get("source") == source
            and record.get("sha256") == expected_sha
            and record.get("signature") == signature,
            "SENDER_RECEIPT_MISMATCH")
    stem = re.sub(r"[^\w. -]", "_", Path(source).stem,
                  flags=re.UNICODE).strip(" ._-")[:120] or "scan"
    require(record.get("destination") ==
            scope + "/" + stem + "--nas-" + expected_sha + ".pdf",
            "SENDER_DESTINATION_MISMATCH")
    return record


def _validate_import(proof, sender, receipt_name):
    require(isinstance(proof, dict) and set(proof) == {
        "schema_version", "bridge_receipt", "receiver_source",
        "sha256", "document_id", "sender_receipt",
    }, "IMPORT_PROOF_SCHEMA")
    require(type(proof["schema_version"]) is int and proof["schema_version"] == 1
            and isinstance(proof["sender_receipt"], str)
            and proof["sender_receipt"] == receipt_name
            and isinstance(proof["bridge_receipt"], str)
            and BRIDGE.fullmatch(proof["bridge_receipt"])
            and isinstance(proof["receiver_source"], str)
            and proof["receiver_source"] == sender["destination"]
            and proof["sha256"] == sender["sha256"]
            and type(proof["document_id"]) is int and proof["document_id"] > 0,
            "IMPORT_PROOF_NOT_BOUND_TO_SENDER")


def _read_json_stdin():
    raw = sys.stdin.buffer.read(16385)
    require(0 < len(raw) <= 16384, "IMPORT_PROOF_TOO_LARGE")
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("DUPLICATE_IMPORT_FIELD")
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _atomic_event(dirfd, name, event):
    raw = (json.dumps(event, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    require(len(raw) <= 4096, "ARCHIVE_EVENT_TOO_LARGE")
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
                 | os.O_CLOEXEC, 0o600, dir_fd=dirfd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(raw)
            f.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(dirfd)


def _noreplace_rename(srcfd, original, dstfd, archived):
    """Use kernel renameat2(RENAME_NOREPLACE), no unsafe plain-rename fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    require(fn is not None, "RENAMEAT2_UNAVAILABLE_NO_FALLBACK")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p,
                   ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    result = fn(srcfd, os.fsencode(original), dstfd,
                os.fsencode(archived), RENAME_NOREPLACE)
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.ENOSYS, errno.EINVAL):
            raise RuntimeError("RENAME_NOREPLACE_UNSUPPORTED")
        raise OSError(code, os.strerror(code))


def archive_one(source_dir, state_dir, scope, filename, proof, *,
                archive_scope_dir, commit=False,
                max_size=MAX_BYTES, quiet_seconds=60,
                archive_month=None, rename_callback=None):
    """Reviewable one-shot routine; only source directory child is selectable.

    Production caller must guarantee: restricted identity, configured approved
    source path, root-owned enable gate, DSM ACL, authenticated live proof,
    backup and scanner write quiescence. Tests inject temp dirs only.
    """
    require(scope in SCOPES and isinstance(filename, str)
            and filename not in ("", ".", "..") and not filename.startswith(".")
            and "/" not in filename and "\\" not in filename
            and "\x00" not in filename and filename.lower().endswith(".pdf")
            and len(filename.encode("utf-8")) <= 255,
            "INVALID_ARCHIVE_SOURCE")
    require(type(commit) is bool and isinstance(source_dir, Path)
            and isinstance(state_dir, Path) and source_dir.is_absolute()
            and state_dir.is_absolute() and ".." not in source_dir.parts
            and ".." not in state_dir.parts,
            "INVALID_ARCHIVE_MODE_OR_PATHS")
    require(type(max_size) is int and 0 < max_size <= MAX_BYTES
            and type(quiet_seconds) is int and 30 <= quiet_seconds <= 3600,
            "INVALID_ARCHIVE_LIMITS")
    require(isinstance(proof, dict), "IMPORT_PROOF_SCHEMA")
    _validate_archive_scope_path(archive_scope_dir, source_dir, scope)
    sync_uid = os.geteuid()
    require(sync_uid != 0, "ROOT_NOT_ALLOWED")
    # Caller selects the approved source directory from immutable site settings.
    # The only filesystem path supplied by the operator is its relative filename.
    state_fd = _check_dir(state_dir, sync_uid)
    try:
        lockst = os.stat("sync.lock", dir_fd=state_fd, follow_symlinks=False)
        require(stat.S_ISREG(lockst.st_mode) and lockst.st_uid == sync_uid
                and lockst.st_nlink == 1 and stat.S_IMODE(lockst.st_mode) == 0o600,
                "UNSAFE_SENDER_LOCK")
        lockfd = os.open("sync.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=state_fd)
        try:
            flock(lockfd, LOCK_EX | LOCK_NB)
            source_before = source_dir.lstat()
            require(stat.S_ISDIR(source_before.st_mode)
                    and source_before.st_nlink >= 1,
                    "UNSAFE_SOURCE_PARENT")
            sourcefd = os.open(source_dir, os.O_RDONLY | os.O_DIRECTORY
                               | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                source_current = os.fstat(sourcefd)
                require((source_before.st_dev, source_before.st_ino,
                         source_before.st_mode) ==
                        (source_current.st_dev, source_current.st_ino,
                         source_current.st_mode),
                        "SOURCE_PARENT_CHANGED")
                source_info = os.stat(filename, dir_fd=sourcefd,
                                      follow_symlinks=False)
                signature = source_signature(source_info)
                require(stat.S_ISREG(source_info.st_mode)
                        and source_info.st_nlink == 1
                        and 0 < source_info.st_size <= max_size
                        and time.time_ns() - max(source_info.st_ctime_ns, source_info.st_mtime_ns)
                        >= quiet_seconds * 1000000000,
                        "SOURCE_NOT_QUIESCENT_OR_UNSAFE")
                sender_id = hashlib.sha256(
                    (scope + "\0" + filename).encode("utf-8")).hexdigest()
                receipt_name = sender_id + ".json"
                receipt = _read_receipt(state_dir / receipt_name, scope,
                                        filename, signature, proof.get("sha256"))
                _validate_import(proof, receipt, receipt_name)
                _read_source(sourcefd, filename, max_size,
                             expected_signature=signature,
                             expected_sha=receipt["sha256"])
                month = archive_month or datetime.datetime.now(
                    datetime.timezone.utc).strftime("%Y-%m")
                require(re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", month)
                        is not None, "INVALID_ARCHIVE_MONTH")
                archfd = _check_dir(archive_scope_dir, sync_uid)
                try:
                    require(os.fstat(archfd).st_dev == os.fstat(sourcefd).st_dev,
                            "ARCHIVE_NOT_SAME_FILESYSTEM")
                    journalfd = _check_dir(state_dir / JOURNAL_DIR, sync_uid)
                    try:
                        # A corrupt/unknown journal must never be ignored.
                        files = os.listdir(journalfd)
                        require(not any(x.startswith(sender_id + ".") for x in files),
                                "ARCHIVE_JOURNAL_ALREADY_EXISTS")
                        final = sender_id + ".pdf"
                        plan = {
                            "schema_version": 1, "archive_type": "same_subvolume_rename",
                            "scope": scope, "source": filename, "sender_receipt": receipt_name,
                            "bridge_receipt": proof["bridge_receipt"],
                            "document_id": proof["document_id"],
                            "sha256": receipt["sha256"], "signature": signature,
                            "archive_month": month, "archive_name": final,
                        }
                        if not commit:
                            return dict(status="ARCHIVE_DRY_RUN", **plan)
                        # Only month subdirectories are created; never auto-
                        # provision archive root or change any DSM ACLs.
                        try:
                            os.mkdir(month, 0o700, dir_fd=archfd)
                            _fsync_dir(archfd)
                        except FileExistsError:
                            pass
                        monthfd = _check_dir(archive_scope_dir / month, sync_uid)
                        try:
                            require(os.fstat(monthfd).st_dev == os.fstat(sourcefd).st_dev,
                                    "ARCHIVE_MONTH_NOT_SAME_FILESYSTEM")
                            try:
                                os.stat(final, dir_fd=monthfd, follow_symlinks=False)
                                raise RuntimeError("ARCHIVE_TARGET_ALREADY_EXISTS")
                            except FileNotFoundError:
                                pass
                            _fsync_existing_pdf(sourcefd, filename, signature)
                            _atomic_event(journalfd, sender_id + ".prepared.json",
                                          dict(plan, stage="ARCHIVE_PREPARED"))
                            # All critical preconditions are rechecked AFTER
                            # durable intent and BEFORE atomic file move.
                            _read_source(sourcefd, filename, max_size,
                                         expected_signature=signature,
                                         expected_sha=receipt["sha256"])
                            mover = rename_callback or _noreplace_rename
                            mover(sourcefd, filename, monthfd, final)
                            _fsync_dir(monthfd)
                            _fsync_dir(sourcefd)
                            # This checks identity *after* move. In case of
                            # any mismatch, archive file is retained and the
                            # journal remains unresolved, requiring recovery.
                            # Linux rename updates inode ctime. Device,
                            # inode, size, mtime and SHA must stay the same,
                            # while ctime may advance after the rename.
                            _read_source(monthfd, final, max_size,
                                         expected_signature=signature,
                                         expected_sha=receipt["sha256"],
                                         after_rename=True)
                            _fsync_existing_pdf(monthfd, final, signature)
                            _atomic_event(journalfd, sender_id + ".archived.json",
                                          dict(plan, stage="ARCHIVED",
                                               archived_at=datetime.datetime.now(
                                                   datetime.timezone.utc).isoformat()))
                            return dict(status="ARCHIVE_MOVED", **plan)
                        finally:
                            os.close(monthfd)
                    finally:
                        os.close(journalfd)
                finally:
                    os.close(archfd)
            finally:
                os.close(sourcefd)
        finally:
            os.close(lockfd)
    finally:
        os.close(state_fd)


def main():
    parser = argparse.ArgumentParser(description="Operator-only, no purge")
    parser.add_argument("--state-parent", required=True)
    parser.add_argument("--only", required=True, help="exact Scope/Filename.pdf")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    parent = Path(args.state_parent)
    require(parent.is_absolute() and parent.parent != parent
            and ".." not in parent.parts, "INVALID_STATE_PARENT")
    bindir = parent / "bin"
    binfo = bindir.lstat()
    require(stat.S_ISDIR(binfo.st_mode) and binfo.st_uid == 0
            and stat.S_IMODE(binfo.st_mode) == 0o755,
            "UNSAFE_ROOT_OWNED_CODE_DIRECTORY")
    sys.path.insert(0, str(bindir))
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state
    require(SETTINGS["parent"] == parent, "SITE_CONFIG_MISMATCH")
    secure_state()
    matches = [(folder, scope, args.only[len(scope) + 1:])
               for folder, scope in SETTINGS["sources"]
               if args.only.startswith(scope + "/")
               and "/" not in args.only[len(scope) + 1:]]
    require(len(matches) == 1, "SOURCE_NOT_IN_SITE_CONFIG")
    source_dir, scope, filename = matches[0]
    site = SITE_BY_SCOPE[scope]
    archive_scope_dir = _validated_protected_scope(
        source_dir, scope, os.geteuid())
    # The historic all-site gate has no authority over protected archives.
    global_gate = parent / "archive-move.enabled"
    require(not global_gate.exists() and not global_gate.is_symlink(),
            "LEGACY_ARCHIVE_GATE_MUST_BE_ABSENT")
    if args.commit:
        _require_site_commit_gate(parent, site)
    proof = _read_json_stdin()
    result = archive_one(source_dir, SETTINGS["state"], scope, filename, proof,
                         archive_scope_dir=archive_scope_dir,
                         commit=args.commit,
                         max_size=SETTINGS["max_size"],
                         quiet_seconds=SETTINGS["quiet"])
    # Do not echo private original names on stdout.
    print(result["status"], result["sender_receipt"],
          result["archive_month"], result["archive_name"])
    print("ARCHIVE_PURGE_DISABLED")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        print("ARCHIVE_MOVE_FAILED", str(exc).split(" ", 1)[0], file=sys.stderr)
        sys.exit(1)
