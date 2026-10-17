#!/usr/bin/env python3
"""OFFLINE FIXTURE ONLY: copy, journal, unlink and restore a mock scan.

Every writable path is restricted to an owner-private direct child of /tmp
named bergen-paperless-archive-fixture-*. NEVER deploy to Synology.
The supplied SENT/import proof is not authenticated. These tests establish
algorithmic safety properties, NOT authority to remove real originals.
No CLI, no scheduler, no live path, no purge, no archive approval API.
"""
import hashlib
import json
import os
import re
import secrets
import stat
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

from match_v2_import_proof_offline import match_offline

ROOT_PREFIX = "bergen-paperless-archive-fixture-"
SCOPES = frozenset({"Privat/thomas", "Privat/nadja", "Eltern", "Familie"})
STAGES = ("QUARANTINE_PREPARED", "ARCHIVED", "SOURCE_REMOVE_INTENT", "SOURCE_REMOVED", "RESTORED")
MAX_SIZE = 512 * 1024 * 1024
RECEIPT_ID = re.compile(r"v2-[0-9a-f]{32}-[0-9a-f]{64}\Z")


def _id(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid,
            st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _require_source_signature(stat_result, sent):
    actual = [stat_result.st_dev, stat_result.st_ino, stat_result.st_size,
              stat_result.st_mtime_ns, stat_result.st_ctime_ns]
    if actual != sent["signature"]:
        raise RuntimeError("ORIGINAL_INCARNATION_CHANGED")


def _dir(path):
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise RuntimeError("UNSAFE_OFFLINE_DIRECTORY")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if _id(os.fstat(fd)) != _id(st):
            raise RuntimeError("OFFLINE_DIRECTORY_CHANGED")
    finally:
        os.close(fd)


def _root(root):
    if (not isinstance(root, Path) or not root.is_absolute()
            or root.parent != Path("/tmp")
            or not root.name.startswith(ROOT_PREFIX)
            or len(root.name) > 100 or ".." in root.parts):
        raise ValueError("OFFLINE_FIXTURE_ROOT_REQUIRED")
    _dir(root)
    for part in ("sources", "quarantine", "state"):
        _dir(root / part)


def _scope_dir(root, top, scope):
    if scope not in SCOPES:
        raise ValueError("UNAPPROVED_SCOPE")
    base = root / top
    if scope.startswith("Privat/"):
        _dir(base / "Privat")
    target = base / scope
    _dir(target)
    return target


def _regular_digest(path, expected, size=None):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= MAX_SIZE
            or (size is not None and before.st_size != size)):
        raise RuntimeError("UNSAFE_OR_CHANGED_OFFLINE_PDF")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if _id(os.fstat(fd)) != _id(before):
            raise RuntimeError("OFFLINE_PDF_RACED")
        h = hashlib.sha256()
        head, tail = b"", b""
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if not head:
                    head = block[:8]
                tail = (tail + block)[-2048:]
                h.update(block)
        if (_id(os.fstat(fd)) != _id(before) or _id(path.lstat()) != _id(before)):
            raise RuntimeError("OFFLINE_PDF_RACED")
        if not head.startswith(b"%PDF-") or b"%%EOF" not in tail:
            raise RuntimeError("OFFLINE_PDF_INVALID")
        if h.hexdigest() != expected:
            raise RuntimeError("OFFLINE_PDF_SHA_MISMATCH")
        return before
    finally:
        os.close(fd)


def _context(root, sent, imported):
    _root(root)
    compared = match_offline(sent, imported)
    if not compared["identity_match"]:
        raise RuntimeError("OFFLINE_IMPORT_MISMATCH")
    scope, source = sent["scope"], sent["source"]
    if (scope not in SCOPES or source in ("", ".", "..")
            or "/" in source or "\\" in source or "\x00" in source
            or not RECEIPT_ID.fullmatch(sent["receipt_id"])):
        raise ValueError("INVALID_FIXTURE_IDENTITY")
    srcdir = _scope_dir(root, "sources", scope)
    archive_dir = _scope_dir(root, "quarantine", scope)
    dest = archive_dir / (sent["receipt_id"] + ".pdf")
    return srcdir / source, dest, compared


def _lock(root):
    file = root / "state" / "sync.lock"
    st = file.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600):
        raise RuntimeError("UNSAFE_FIXTURE_LOCK")
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if _id(os.fstat(fd)) != _id(st):
            raise RuntimeError("FIXTURE_LOCK_CHANGED")
        flock(fd, LOCK_EX | LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _journal_event(root, sent, stage, imported):
    if stage not in STAGES:
        raise ValueError("UNSUPPORTED_FIXTURE_STAGE")
    return {
        "schema_version": 1, "stage": stage, "receipt_id": sent["receipt_id"],
        "scope": sent["scope"], "source": sent["source"],
        "sha256": sent["sha256"], "destination": sent["destination"],
        "document_id": imported["document_id"],
    }


def _event_path(root, sent, stage):
    return root / "state" / (sent["receipt_id"] + "." + stage.lower() + ".json")


def _event_bytes(event):
    return (json.dumps(event, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _publish(root, sent, stage, imported):
    """Create-only + two fsyncs; a published event must never be overwritten."""
    path = _event_path(root, sent, stage)
    content = _event_bytes(_journal_event(root, sent, stage, imported))
    temp = path.parent / (".fixture-" + secrets.token_hex(16))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.link(temp, path, follow_symlinks=False)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)
        _fsync_dir(path.parent)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_event(root, sent, stage, imported):
    path = _event_path(root, sent, stage)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > 4096):
        raise RuntimeError("UNSAFE_FIXTURE_JOURNAL")
    if path.read_bytes() != _event_bytes(_journal_event(root, sent, stage, imported)):
        raise RuntimeError("FIXTURE_JOURNAL_CHANGED")


def _no_existing_events(root, sent):
    if any(_event_path(root, sent, stage).exists() for stage in STAGES):
        raise RuntimeError("UNRESOLVED_QUARANTINE_REQUIRES_RECONCILIATION")


def _copy_private(source, destination, size, digest):
    """Copy between paths even across mounts; never assumes rename atomicity."""
    temp = destination.parent / (".pending-" + secrets.token_hex(16))
    source_stat = _regular_digest(source, digest, size)
    sfd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    dfd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                  0o600)
    try:
        try:
            if _id(os.fstat(sfd)) != _id(source_stat):
                raise RuntimeError("FIXTURE_SOURCE_CHANGED")
            h = hashlib.sha256()
            with os.fdopen(sfd, "rb", closefd=False) as inp, os.fdopen(dfd, "wb", closefd=False) as out:
                for part in iter(lambda: inp.read(1024 * 1024), b""):
                    h.update(part)
                    out.write(part)
                out.flush()
                os.fsync(out.fileno())
            if h.hexdigest() != digest:
                raise RuntimeError("FIXTURE_SOURCE_CHANGED")
            if (_id(os.fstat(sfd)) != _id(source_stat)
                    or _id(source.lstat()) != _id(source_stat)):
                raise RuntimeError("FIXTURE_SOURCE_CHANGED")
        finally:
            os.close(sfd)
            os.close(dfd)
        _regular_digest(temp, digest, size)
        _regular_digest(source, digest, size)
        # Atomic create-only publication *within the quarantine directory*.
        # This link does not cross source/quarantine filesystem boundaries.
        os.link(temp, destination, follow_symlinks=False)
        _fsync_dir(destination.parent)
    finally:
        temp.unlink(missing_ok=True)
        _fsync_dir(destination.parent)


def archive_fixture(root, sent, imported):
    """Create a complete durable private copy; does not remove original."""
    source, dest, _ = _context(root, sent, imported)
    fd = _lock(root)
    try:
        _no_existing_events(root, sent)
        original = _regular_digest(source, sent["sha256"], sent["signature"][2])
        _require_source_signature(original, sent)
        if dest.exists() or dest.is_symlink():
            raise RuntimeError("ARCHIVE_DESTINATION_ALREADY_EXISTS")
        _publish(root, sent, "QUARANTINE_PREPARED", imported)
        _copy_private(source, dest, sent["signature"][2], sent["sha256"])
        _regular_digest(dest, sent["sha256"], sent["signature"][2])
        _require_source_signature(
            _regular_digest(source, sent["sha256"], sent["signature"][2]), sent)
        _publish(root, sent, "ARCHIVED", imported)
        return {"quarantine_copy_verified": True, "source_present": True,
                "source_delete_authorized": False, "production_approved": False}
    finally:
        os.close(fd)


def delete_fixture_original(root, sent, imported, *, offline_restore_test_confirmed=False):
    """Remove only a fixture original AFTER an independent fixture restore test.

    This is NOT a production approval interface; trusted import/backup
    evidence is absent and the /tmp restriction is deliberately permanent.
    """
    if offline_restore_test_confirmed is not True:
        raise RuntimeError("RESTORE_TEST_REQUIRED")
    source, dest, _ = _context(root, sent, imported)
    fd = _lock(root)
    try:
        _require_event(root, sent, "QUARANTINE_PREPARED", imported)
        _require_event(root, sent, "ARCHIVED", imported)
        if any(_event_path(root, sent, s).exists() for s in STAGES[2:]):
            raise RuntimeError("SOURCE_REMOVAL_ALREADY_ATTEMPTED")
        expected = sent["signature"][2]
        _regular_digest(dest, sent["sha256"], expected)
        old = _regular_digest(source, sent["sha256"], expected)
        _require_source_signature(old, sent)
        _publish(root, sent, "SOURCE_REMOVE_INTENT", imported)
        # Checked destination remains preserved even on a crash during unlink.
        _regular_digest(dest, sent["sha256"], expected)
        if _id(source.lstat()) != _id(old):
            raise RuntimeError("SOURCE_CHANGED_BEFORE_UNLINK")
        source.unlink()
        _fsync_dir(source.parent)
        _publish(root, sent, "SOURCE_REMOVED", imported)
        return {"fixture_source_removed": True, "quarantine_copy_retained": True,
                "production_approved": False}
    finally:
        os.close(fd)


def restore_fixture_original(root, sent, imported):
    """Create-only restore of a deleted fixture original, without retransmission."""
    source, dest, _ = _context(root, sent, imported)
    fd = _lock(root)
    try:
        for stage in STAGES[:4]:
            _require_event(root, sent, stage, imported)
        if _event_path(root, sent, "RESTORED").exists():
            raise RuntimeError("FIXTURE_RESTORE_ALREADY_RECORDED")
        if source.exists() or source.is_symlink():
            raise RuntimeError("SOURCE_ALREADY_EXISTS")
        _regular_digest(dest, sent["sha256"], sent["signature"][2])
        sfd = os.open(dest, os.O_RDONLY | os.O_NOFOLLOW)
        dfd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(sfd, "rb", closefd=False) as inp, os.fdopen(dfd, "wb", closefd=False) as out:
                for part in iter(lambda: inp.read(1024 * 1024), b""):
                    out.write(part)
                out.flush()
                os.fsync(out.fileno())
        finally:
            os.close(sfd)
            os.close(dfd)
        _fsync_dir(source.parent)
        _regular_digest(source, sent["sha256"], sent["signature"][2])
        _publish(root, sent, "RESTORED", imported)
        return {"fixture_restored": True, "production_approved": False}
    finally:
        os.close(fd)


__all__ = ["archive_fixture", "delete_fixture_original", "restore_fixture_original"]
