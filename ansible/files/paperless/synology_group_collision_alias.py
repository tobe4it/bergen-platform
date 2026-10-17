#!/usr/bin/env python3
"""Resolve post-archive SAME-NAME GROUP scans without overwriting v1 receipts.

Live integration is only via synology_scan_sync.scan(), under its sync.lock,
as the restricted NAS sync user with the root-owned scheduled sender gate.
The previous document MUST have a complete protected NAS archive journal,
matching original SENT receipt, and a byte-verified archived PDF.

Rename ONLY the new stable intake PDF, on the same filesystem, with kernel
renameat2(RENAME_NOREPLACE) into a collision-free nonce-suffixed basename.
The PDF bytes are unchanged. v1 treats the renamed scan as a new independent
source and retains all historical v1 receipts and original archive journals.
No Paperless import is claimed and no archive/delete is authorized here.

An original overwritten BEFORE its verified archival is NOT recoverable by
this helper and must STOP for manual review. No fallback to a plain rename.
"""
import hashlib
import os
import pwd
import secrets
import stat
import time
from pathlib import Path

GROUPS = frozenset(("Familie", "Eltern"))
MAX_SCAN_NAME_BYTES = 255
COLLISION_TAG = "--scan-"


def alias_basename(original, nonce):
    """Preserve source filename prefix, never exceed filesystem byte limit."""
    if (not isinstance(original, str) or not original.lower().endswith(".pdf")
            or original in (".", "..") or original.startswith(".")
            or "/" in original or "\\" in original
            or any(ord(c) < 32 or ord(c) == 127 for c in original)
            or not isinstance(nonce, str) or len(nonce) != 32
            or any(ch not in "0123456789abcdef" for ch in nonce)):
        raise ValueError("INVALID_COLLISION_SOURCE")
    suffix = COLLISION_TAG + nonce + ".pdf"
    allowed = MAX_SCAN_NAME_BYTES - len(suffix.encode("ascii"))
    # Legacy v1 sender truncates its *receiver* stem at 120 code points.
    # Keep the entire nonce inside those 120 to avoid same-digest collisions
    # even for two source filenames with the same very long prefix.
    stem = original[:-4][:75]
    while stem and len(stem.encode("utf-8")) > allowed:
        stem = stem[:-1]
    if not stem:
        raise RuntimeError("COLLISION_SOURCE_STEM_UNUSABLE")
    return stem + suffix


def require_previous_archived(state, folder, scope, name, receipt):
    """Inspect native reviewed v1 archive evidence without assuming old absent.

    This is called with sender sync.lock held. The global archived-source
    audit cannot be called because a *new* source now has the old basename.
    Verify every archive-journal pair and the specific prior archived PDF.
    """
    import audit_synology_completed_archive_moves as audit
    import synology_same_volume_archive_move as move

    key = hashlib.sha256((scope + "\0" + name).encode("utf-8")).hexdigest()
    if (receipt.get("status") != "SENT" or
            receipt.get("scope") != scope or receipt.get("source") != name or
            receipt.get("signature") is None or
            receipt.get("sha256") is None):
        raise RuntimeError("PRIOR_RECEIPT_NOT_SENT")
    uid = os.geteuid()
    journalfd = move._check_dir(state / move.JOURNAL_DIR, uid)
    try:
        entries = os.listdir(journalfd)
        all_events = audit.inspect_events(
            entries, lambda entry: audit.read_event(journalfd, entry, uid))
    finally:
        os.close(journalfd)

    stages = all_events.get(key)
    if stages is None:
        raise RuntimeError("NAME_REUSED_BEFORE_VERIFIED_ARCHIVE")
    event = stages["archived"]
    if (event.get("scope") != scope or event.get("source") != name
            or event.get("sender_receipt") != key + ".json"
            or event.get("signature") != receipt["signature"]
            or event.get("sha256") != receipt["sha256"]
            or event.get("archive_site") != move.SITE_BY_SCOPE[scope]
            or event.get("archive_name") != key + ".pdf"):
        raise RuntimeError("PRIOR_ARCHIVE_RECEIPT_MISMATCH")

    # Check original v1 sender receipt using the exact reviewed worker.
    prior = move._read_receipt(
        state / (key + ".json"), scope, name,
        event["signature"], event["sha256"])
    if prior["destination"] != receipt.get("destination"):
        raise RuntimeError("PRIOR_RECEIVER_RECEIPT_MISMATCH")

    protected = move._validated_protected_scope(folder, scope, uid)
    if event.get("archive_scope_dir") != str(protected):
        raise RuntimeError("PRIOR_ARCHIVE_SCOPE_MISMATCH")
    monthfd = move._check_dir(protected / event["archive_month"], uid)
    try:
        audit.inspect_pdf(monthfd, event["archive_name"],
                          event["signature"], event["sha256"],
                          512 * 1024 * 1024)
    finally:
        os.close(monthfd)
    return event


def resolve_under_sender_lock(folder, scope, source, receipt, *, state,
                              quiet_seconds, rename=None, nonce_factory=None):
    """Resolve one same-name NEW GROUP scan; no data or historical proof loss.

    Caller MUST hold the active v1 sender's sync.lock and have verified the
    root-owned sender schedule gate. Abort on metadata-only changes.
    """
    import synology_scan_sync as sync
    import synology_same_volume_archive_move as move

    if (scope not in GROUPS or not isinstance(folder, Path)
            or not folder.is_absolute() or not isinstance(source, Path)
            or source.parent != folder or not isinstance(state, Path)
            or not state.is_absolute()
            or os.geteuid() == 0
            or os.geteuid() != pwd.getpwnam(sync.SETTINGS["sync_user"]).pw_uid):
        raise RuntimeError("GROUP_COLLISION_SCOPE_OR_USER_INVALID")
    sync.secure_state()
    sync.require_schedule_gate()

    old_sig = receipt.get("signature")
    if (not isinstance(old_sig, list) or len(old_sig) != 5
            or any(type(x) is not int or x < 0 for x in old_sig)):
        raise RuntimeError("INVALID_PREVIOUS_SOURCE_SIGNATURE")
    old = sync.metadata(source)
    old_current_sig = sync.signature(old)
    if old_current_sig == old_sig:
        raise RuntimeError("NO_SOURCE_COLLISION_TO_RESOLVE")
    if time.time_ns() - max(old.st_mtime_ns, old.st_ctime_ns) < quiet_seconds * 1000000000:
        return None

    # An archived original inode cannot simultaneously be the new source.
    # If inode is the same, this is an ACL/metadata change or unarchived
    # in-place rewrite. Do not turn it into a new import.
    if old_sig[:2] == old_current_sig[:2]:
        raise RuntimeError("OLD_INODE_STILL_ACTIVE_REQUIRES_REVIEW")

    require_previous_archived(state, folder, scope, source.name, receipt)
    with __import__("tempfile").TemporaryDirectory(
            dir=state, prefix="group-collision-") as tmp:
        snapshot = Path(tmp) / "check.pdf"
        checked = sync.snapshot(source, snapshot)
        if checked is None:
            return None
        digest, snapshot_sig = checked
        if snapshot_sig != old_current_sig:
            return None

    # The receiver filename of the previous import never changes. New
    # basename generates an independent *legacy* sender key and destination.
    nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
    alias = alias_basename(source.name, nonce_factory())
    target = folder / alias
    if sync.receipt_path(scope, alias).exists():
        raise RuntimeError("COLLISION_ALIAS_HAS_RECEIPT")
    dirfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.stat(source.name, dir_fd=dirfd, follow_symlinks=False)
        if sync.signature(before) != old_current_sig:
            return None
        (rename or move._noreplace_rename)(dirfd, source.name, dirfd, alias)
        # A crash after successful rename but before receipt creation is
        # recoverable: the alias remains in the intake folder for v1 sender.
        os.fsync(dirfd)
        new_stat = sync.metadata(target)
        if (new_stat.st_dev, new_stat.st_ino, new_stat.st_size,
                new_stat.st_mtime_ns) != (
                old.st_dev, old.st_ino, old.st_size, old.st_mtime_ns):
            raise RuntimeError("COLLISION_SOURCE_CHANGED_DURING_RENAME")
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if sync.signature(os.fstat(fd))[:4] != old_current_sig[:4]:
                raise RuntimeError("COLLISION_RENAMED_INODE_CHANGED")
            hasher = hashlib.sha256()
            with os.fdopen(fd, "rb", closefd=False) as pdf:
                for part in iter(lambda: pdf.read(1024 * 1024), b""):
                    hasher.update(part)
            if (hasher.hexdigest() != digest or
                    sync.signature(os.fstat(fd))[:4] != old_current_sig[:4] or
                    sync.signature(sync.metadata(target))[:4] != old_current_sig[:4]):
                raise RuntimeError("COLLISION_RENAMED_PDF_CHANGED")
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)
    print("GROUP_SAME_NAME_NEW_INSTANCE_RENAMED", scope, "(private name omitted)",
          flush=True)
    return target


__all__ = ["alias_basename", "require_previous_archived",
           "resolve_under_sender_lock"]
