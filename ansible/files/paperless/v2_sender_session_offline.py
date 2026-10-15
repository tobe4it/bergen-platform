#!/usr/bin/env python3
"""OFFLINE ONLY: fail-closed v2 one-attempt transfer session state machine.

Does not launch processes, connect to NAS/LXC, publish SENT, archive, or delete.
Injected callbacks are MOCKS, not authenticated remote evidence. This module
must not be installed on DSM or used to approve live sender activation.

Durably publish PREPARED before any callback. A crash or timeout after that
point intentionally leaves an unresolved journal event and blocks retries.
"""
import copy
import hashlib
import os
import secrets
import stat
import tempfile
from pathlib import Path

import compare_v2_transfer_evidence_offline as compare
import synology_receipt_v2_store as store

MAX_BYTES = 512 * 1024 * 1024


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _sig(st):
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def _open_source(source):
    if (not isinstance(source, Path) or not source.is_absolute()
            or ".." in source.parts or source.name in ("", ".", "..")
            or not source.name.lower().endswith(".pdf")):
        raise ValueError("INVALID_OFFLINE_SOURCE")
    before = source.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1 or not 0 < before.st_size <= MAX_BYTES):
        raise RuntimeError("UNSAFE_OFFLINE_SOURCE")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if _identity(os.fstat(fd)) != _identity(before):
            raise RuntimeError("OFFLINE_SOURCE_CHANGED_BEFORE_OPEN")
        return fd, before
    except BaseException:
        os.close(fd)
        raise


def _copy_snapshot(source, dest):
    fd, before = _open_source(source)
    hasher = hashlib.sha256()
    head = b""
    tail = b""
    try:
        outfd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                        | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "rb", closefd=False) as inp, os.fdopen(outfd, "wb", closefd=False) as out:
                while True:
                    part = inp.read(1024 * 1024)
                    if not part:
                        break
                    if not head:
                        head = part[:8]
                    tail = (tail + part)[-2048:]
                    hasher.update(part)
                    out.write(part)
                out.flush()
                os.fsync(out.fileno())
        finally:
            os.close(outfd)
        if (_identity(os.fstat(fd)) != _identity(before)
                or _identity(source.lstat()) != _identity(before)):
            raise RuntimeError("OFFLINE_SOURCE_CHANGED_DURING_SNAPSHOT")
        if not head.startswith(b"%PDF-") or b"%%EOF" not in tail:
            raise RuntimeError("INVALID_OFFLINE_PDF")
        if dest.stat().st_size != before.st_size:
            raise RuntimeError("OFFLINE_SNAPSHOT_SIZE_MISMATCH")
        return before, hasher.hexdigest()
    finally:
        os.close(fd)


def _recheck_source(source, expected_stat, expected_digest):
    fd, st = _open_source(source)
    try:
        if _identity(st) != _identity(expected_stat):
            raise RuntimeError("OFFLINE_SOURCE_CHANGED_AFTER_TRANSFER")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as inp:
            for block in iter(lambda: inp.read(1024 * 1024), b""):
                digest.update(block)
        if (_identity(os.fstat(fd)) != _identity(expected_stat)
                or _identity(source.lstat()) != _identity(expected_stat)
                or digest.hexdigest() != expected_digest):
            raise RuntimeError("OFFLINE_SOURCE_CHANGED_AFTER_TRANSFER")
    finally:
        os.close(fd)


def run_offline_once(journal, source, scope, transport_mock, receiver_mock):
    """Run ONE synthetic session; never retry and never commit SENT.

    The callbacks are deliberately injected in lieu of real process execution:
        transport_mock(snapshot_path, deepcopied_prepared) -> (rc, out, err)
        receiver_mock(deepcopied_prepared) -> (rc, out)
    Even perfectly matching callback outputs remain UNAUTHENTICATED.
    """
    if not callable(transport_mock) or not callable(receiver_mock):
        raise ValueError("OFFLINE_CALLBACKS_REQUIRED")
    store.validate(scope, source.name if isinstance(source, Path) else "",
                   "0" * 64, [0, 0, 1, 0, 0])
    dirfd = store._directory_fd(journal)
    try:
        lockfd = store._lock_existing(dirfd)
        try:
            if (scope, source.name) in store._checked_history(dirfd):
                raise RuntimeError("EXISTING_RECEIPT_BLOCKS_RETRANSMISSION")

            with tempfile.TemporaryDirectory(prefix="bergen-v2-offline-") as temp:
                snapshot = Path(temp) / "frozen.pdf"
                st, digest = _copy_snapshot(source, snapshot)
                prepared = store.prepared_record(
                    scope, source.name, digest, _sig(st), secrets.token_hex(16))
                recorded_bytes = store._canonical(prepared)
                prepared_name = prepared["receipt_id"] + ".prepared.json"

                # The immutable PREPARED is fully durable before the first
                # transport callback can run. A mid-flight crash blocks retry.
                if not store._publish_no_replace(dirfd, prepared_name, recorded_bytes):
                    raise RuntimeError("PREPARED_ALREADY_PRESENT")
                if store._read_checked(dirfd, prepared_name) != recorded_bytes:
                    raise RuntimeError("PREPARED_NOT_DURABLE")

                transport_result = transport_mock(snapshot, copy.deepcopy(prepared))
                if (not isinstance(transport_result, tuple)
                        or len(transport_result) != 3):
                    raise ValueError("INVALID_TRANSPORT_CALLBACK")
                rc, stdout, stderr = transport_result
                # Fail immediately: do not call the receiver on ambiguous or
                # failed transport. The PREPARED remains unresolved.
                if type(rc) is not int or rc != 0 or stderr != "":
                    raise RuntimeError("OFFLINE_RSYNC_NOT_VERIFIED")
                compare._rsync_new_file(
                    stdout, prepared["destination"].rsplit("/", 1)[1])

                if store._read_checked(dirfd, prepared_name) != recorded_bytes:
                    raise RuntimeError("PREPARED_CHANGED_AFTER_RSYNC")
                _recheck_source(source, st, digest)

                receiver_result = receiver_mock(copy.deepcopy(prepared))
                if (not isinstance(receiver_result, tuple)
                        or len(receiver_result) != 2):
                    raise ValueError("INVALID_RECEIVER_CALLBACK")
                receiver_rc, receiver_stdout = receiver_result
                observed = compare.compare_offline(
                    prepared, rc, stdout, stderr, receiver_rc, receiver_stdout)

                if store._read_checked(dirfd, prepared_name) != recorded_bytes:
                    raise RuntimeError("PREPARED_CHANGED_AFTER_RECEIVER")
                _recheck_source(source, st, digest)

                # Deliberately never create SENT; no authenticated transport
                # or receiver provenance is available in this offline stage.
                if (observed["origin_authenticated"]
                        or observed["sent_authorized"]
                        or observed["source_delete_authorized"]):
                    raise RuntimeError("UNAUTHORIZED_PROOF_ELEVATION")
                return dict(observed,
                            prepared_persisted=True,
                            transport_callback_used=True,
                            receiver_callback_used=True,
                            session_status="UNRESOLVED_AWAITING_TRUSTED_ORCHESTRATOR")
        finally:
            os.close(lockfd)
    finally:
        os.close(dirfd)


__all__ = ["run_offline_once"]
