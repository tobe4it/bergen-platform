#!/usr/bin/env python3
"""READ-ONLY locked audit of EVERY completed v1 NAS same-subvolume archive.

Only complete PREPARED+ARCHIVED journals with matching canonical contents,
source-absence, original SENT receipt, same inode/device and hashed archive
PDF may be exported. Unknown, dangling or duplicate journals and orphan
archive files fail closed. No mkdir/rename/unlink/chmod/receipt writes.
Run as the restricted paperless-sync NAS user; never as root.
"""
import datetime
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

EVENT = re.compile(r"([0-9a-f]{64})[.](prepared|archived)[.]json\Z")
MONTH = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])\Z")
SCOPES = ("Familie", "Eltern", "Privat/thomas", "Privat/nadja")
MAX_EVENTS = 20000


def demand(value, label):
    if not value:
        raise RuntimeError(label)


def strict(pairs):
    result = {}
    for key, value in pairs:
        demand(key not in result, "DUPLICATE_ARCHIVE_EVENT_KEY")
        result[key] = value
    return result


def read_event(dirfd, name, uid):
    initial = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    demand(stat.S_ISREG(initial.st_mode) and initial.st_uid == uid
           and initial.st_nlink == 1 and stat.S_IMODE(initial.st_mode) == 0o600
           and 0 < initial.st_size <= 4096, "UNSAFE_ARCHIVE_EVENT")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    try:
        opened = os.fstat(fd)
        demand((opened.st_dev, opened.st_ino, opened.st_uid, opened.st_mode,
                opened.st_size, opened.st_nlink) ==
               (initial.st_dev, initial.st_ino, initial.st_uid, initial.st_mode,
                initial.st_size, initial.st_nlink), "ARCHIVE_EVENT_CHANGED")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(4097)
        demand(len(raw) == initial.st_size, "ARCHIVE_EVENT_CHANGED")
    finally:
        os.close(fd)
    item = json.loads(raw, object_pairs_hook=strict)
    demand(isinstance(item, dict), "INVALID_ARCHIVE_EVENT")
    canonical = (json.dumps(item, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    demand(raw == canonical, "NONCANONICAL_ARCHIVE_EVENT")
    return item


def inspect_events(entries, reader):
    """Pure structural integrity check shared by offline synthetic tests."""
    demand(len(entries) <= MAX_EVENTS and
           all(isinstance(x, str) and EVENT.fullmatch(x) for x in entries),
           "UNEXPECTED_ARCHIVE_JOURNAL_ENTRY")
    events = {}
    for entry in entries:
        key, stage = EVENT.fullmatch(entry).groups()
        demand(stage not in events.setdefault(key, {}),
               "DUPLICATE_ARCHIVE_EVENT")
        events[key][stage] = reader(entry)
    for key, pair in events.items():
        demand(set(pair) == {"prepared", "archived"},
               "INCOMPLETE_ARCHIVE_JOURNAL")
        prepared = pair["prepared"]
        archived = pair["archived"]
        expected = {
            "schema_version", "archive_type", "scope", "source",
            "sender_receipt", "bridge_receipt", "document_id", "sha256",
            "signature", "archive_site", "archive_scope_dir",
            "archive_month", "archive_name",
        }
        demand(set(prepared) == expected | {"stage"} and
               set(archived) == expected | {"stage", "archived_at"} and
               prepared.get("stage") == "ARCHIVE_PREPARED" and
               archived.get("stage") == "ARCHIVED" and
               all(archived.get(k) == prepared.get(k) for k in expected),
               "CONFLICTING_ARCHIVE_JOURNAL")
        demand(prepared.get("schema_version") == 1 and
               type(prepared.get("schema_version")) is int and
               prepared.get("archive_type") == "same_subvolume_rename" and
               isinstance(prepared.get("archive_month"), str) and
               MONTH.fullmatch(prepared["archive_month"]) and
               prepared.get("sender_receipt") == key + ".json" and
               prepared.get("archive_name") == key + ".pdf" and
               isinstance(prepared.get("sha256"), str) and
               re.fullmatch(r"[0-9a-f]{64}", prepared["sha256"]) and
               isinstance(prepared.get("bridge_receipt"), str) and
               re.fullmatch(r"[0-9a-f]{24}[.]json", prepared["bridge_receipt"]) and
               type(prepared.get("document_id")) is int and
               prepared["document_id"] > 0, "INVALID_ARCHIVE_JOURNAL_IDENTITY")
        sig = prepared.get("signature")
        demand(isinstance(sig, list) and len(sig) == 5 and
               all(type(x) is int and x >= 0 for x in sig),
               "INVALID_ARCHIVE_SIGNATURE")
        try:
            when = datetime.datetime.fromisoformat(archived["archived_at"])
        except (TypeError, ValueError, KeyError):
            raise RuntimeError("INVALID_ARCHIVE_TIMESTAMP") from None
        demand(when.tzinfo is not None and
               when.utcoffset() == datetime.timedelta(0),
               "INVALID_ARCHIVE_TIMESTAMP")
    return events


def inspect_pdf(fd, name, signature, sha, limit):
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    demand(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
           0 < st.st_size <= limit and
           [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns] == signature[:4] and
           st.st_ctime_ns >= signature[4],
           "ARCHIVED_INODE_OR_SIGNATURE_MISMATCH")
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                      dir_fd=fd)
    try:
        opened = os.fstat(file_fd)
        demand((opened.st_dev, opened.st_ino, opened.st_size,
                opened.st_mtime_ns, opened.st_ctime_ns) ==
               (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns,
                st.st_ctime_ns), "ARCHIVED_PDF_CHANGED")
        checksum = hashlib.sha256()
        first, tail = b"", b""
        with os.fdopen(file_fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024*1024), b""):
                if not first:
                    first = block[:8]
                tail = (tail + block)[-2048:]
                checksum.update(block)
        demand(os.fstat(file_fd).st_ctime_ns == st.st_ctime_ns and
               os.stat(name, dir_fd=fd, follow_symlinks=False).st_ino == st.st_ino,
               "ARCHIVED_PDF_CHANGED")
    finally:
        os.close(file_fd)
    demand(first.startswith(b"%PDF-") and b"%%EOF" in tail and
           checksum.hexdigest() == sha, "ARCHIVED_PDF_INVALID_OR_SHA_MISMATCH")


def audit(parent):
    demand(parent.is_absolute() and parent != Path("/") and
           ".." not in parent.parts, "INVALID_ARCHIVE_STATE_PARENT")
    sys.path.insert(0, str(parent / "bin"))
    import synology_same_volume_archive_move as move
    from synology_config import SETTINGS
    from synology_scan_sync import secure_state
    user = pwd.getpwnam(SETTINGS["sync_user"])
    demand(os.geteuid() == user.pw_uid and os.geteuid() != 0 and
           SETTINGS["parent"] == parent, "RESTRICTED_ARCHIVE_AUDITOR_REQUIRED")
    code = (parent / "bin" / "synology_same_volume_archive_move.py").lstat()
    demand(stat.S_ISREG(code.st_mode) and code.st_uid == 0 and
           stat.S_IMODE(code.st_mode) == 0o644 and
           code.st_nlink == 1, "UNTRUSTED_ARCHIVE_WORKER_CODE")
    secure_state()
    state = SETTINGS["state"]
    lockst = (state / "sync.lock").lstat()
    demand(stat.S_ISREG(lockst.st_mode) and lockst.st_uid == os.geteuid()
           and lockst.st_nlink == 1 and stat.S_IMODE(lockst.st_mode) == 0o600,
           "UNSAFE_ARCHIVE_AUDIT_LOCK")
    lfd = os.open(state / "sync.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        flock(lfd, LOCK_EX | LOCK_NB)
        journalfd = move._check_dir(state / move.JOURNAL_DIR, os.geteuid())
        try:
            entries = os.listdir(journalfd)
            eventmap = inspect_events(
                entries, lambda name: read_event(journalfd, name, os.geteuid()))
        finally:
            os.close(journalfd)
        demand(len(SETTINGS["sources"]) == 4 and
               {scope for _, scope in SETTINGS["sources"]} == set(SCOPES),
               "UNEXPECTED_ARCHIVE_AUDIT_SCOPES")
        exported = []
        audited_targets = set()
        archived_sources = set()
        for folder, scope in SETTINGS["sources"]:
            protected_scope = move._validated_protected_scope(
                folder, scope, os.geteuid())
            archfd = move._check_dir(protected_scope, os.geteuid())
            try:
                expected = {
                    key: pair["archived"] for key, pair in eventmap.items()
                    if pair["archived"]["scope"] == scope
                }
                for key, event in expected.items():
                    name = event.get("source")
                    demand(isinstance(name, str) and
                           name not in ("", ".", "..") and not name.startswith(".")
                           and "/" not in name and "\\" not in name and
                           name.lower().endswith(".pdf") and
                           len(name.encode("utf-8")) <= 255,
                           "INVALID_ARCHIVED_SOURCE")
                    demand(event["archive_site"] == move.SITE_BY_SCOPE[scope] and
                           event["archive_scope_dir"] == str(protected_scope) and
                           hashlib.sha256((scope + "\0" + name).encode("utf-8")).hexdigest() == key,
                           "ARCHIVED_SOURCE_IDENTITY_MISMATCH")
                    try:
                        (folder / name).lstat()
                    except FileNotFoundError:
                        pass
                    else:
                        raise RuntimeError("SOURCE_AND_ARCHIVE_BOTH_PRESENT")
                    receipt = move._read_receipt(
                        state / (key + ".json"), scope, name,
                        event["signature"], event["sha256"])
                    demand(receipt["destination"].startswith(scope + "/"),
                           "ARCHIVED_RECEIVER_SCOPE_MISMATCH")
                    monthfd = move._check_dir(
                        protected_scope / event["archive_month"], os.geteuid())
                    try:
                        demand(os.fstat(monthfd).st_dev == event["signature"][0],
                               "ARCHIVED_CROSS_DEVICE")
                        inspect_pdf(monthfd, event["archive_name"],
                                    event["signature"], event["sha256"],
                                    SETTINGS["max_size"])
                    finally:
                        os.close(monthfd)
                    audited_targets.add((scope, event["archive_month"],
                                         event["archive_name"]))
                    archived_sources.add((scope, name))
                    exported.append({
                        "schema_version": 1,
                        "sender_receipt": key + ".json",
                        "scope": scope,
                        "source": name,
                        "receiver_source": receipt["destination"],
                        "sha256": event["sha256"],
                        "bridge_receipt": event["bridge_receipt"],
                        "document_id": event["document_id"],
                        "archive_site": event["archive_site"],
                        "archive_month": event["archive_month"],
                        "archive_name": event["archive_name"],
                        "signature": event["signature"],
                    })
                # Also reject any archive PDF which has no complete journal.
                for month in os.listdir(archfd):
                    demand(MONTH.fullmatch(month) is not None,
                           "UNEXPECTED_PROTECTED_ARCHIVE_ENTRY")
                    monthfd = move._check_dir(protected_scope / month,
                                               os.geteuid())
                    try:
                        for filename in os.listdir(monthfd):
                            demand((scope, month, filename) in audited_targets,
                                   "UNJOURNALED_ARCHIVED_FILE")
                    finally:
                        os.close(monthfd)
            finally:
                os.close(archfd)
        demand(len(exported) == len(eventmap) and
               len(archived_sources) == len(exported) and
               len(audited_targets) == len(exported),
               "ARCHIVE_EVIDENCE_INCOMPLETE")
        for row in sorted(exported, key=lambda x: (x["scope"], x["source"])):
            print(json.dumps(row, sort_keys=True, ensure_ascii=True),
                  flush=True)
        print("NO_FILES_CHANGED", flush=True)
    finally:
        os.close(lfd)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: ... STATE_PARENT")
    audit(Path(sys.argv[1]))
