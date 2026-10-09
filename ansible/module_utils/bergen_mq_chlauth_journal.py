"""Crash-visible local journal for future scoped IBM MQ CHLAUTH fixtures.

This library never contacts MQ and does not confer MQ ownership. Its POSIX
flock is cooperative on one controller, not a distributed/queue-manager
lock. A future writer must separately recheck absence, exclusive control,
and independently verify every MQ object after each write and at cleanup.

A journal is append-only, fsynced after every event, and digest-chained to
detect accidental damage. The digest is not a tamper-proof signature.
Unfinished journals prohibit starting another fixture via this library.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .bergen_mq_audit_names import RUN


_RUN = RUN
_OPS = frozenset((
    "add_deny", "define_receiver", "add_allow",
    "remove_allow", "delete_receiver", "remove_deny",
))
_RESULT = frozenset(("ACKED", "FAILED", "UNKNOWN"))
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class JournalError(RuntimeError):
    pass


def _safe_directory(directory):
    path = Path(directory)
    if not path.is_absolute():
        raise JournalError("Journal directory must be absolute")
    if path.is_symlink():
        raise JournalError("Journal directory must not be a symlink")
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode)
            or stat.S_IMODE(st.st_mode) != 0o700
            or st.st_uid != os.geteuid()):
        raise JournalError("Journal directory must be owned and mode 0700")
    return path


def _read_events(path):
    fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()):
            raise JournalError("Journal must be an owned mode-0600 regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read()
    finally:
        os.close(fd)
    if not data or not data.endswith(b"\n"):
        raise JournalError("Missing, empty or truncated journal")
    previous = "0" * 64
    entries = []
    for number, line in enumerate(data.splitlines(), start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise JournalError("Unparseable journal record") from exc
        if (not isinstance(record, dict)
                or set(record) != {"seq", "prev", "kind", "data", "digest"}
                or type(record["seq"]) is not int or record["seq"] != number
                or record["prev"] != previous
                or not isinstance(record["kind"], str)
                or not isinstance(record["data"], dict)):
            raise JournalError("Journal sequence or chain invalid")
        envelope = {key: record[key] for key in ("seq", "prev", "kind", "data")}
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        actual = hashlib.sha256(encoded).hexdigest()
        if record["digest"] != actual:
            raise JournalError("Journal checksum mismatch")
        previous = actual
        entries.append(record)
    _validate_event_sequence(entries, path)
    return entries


def _validate_event_sequence(entries, path):
    """Validate meanings and transitions, not just record digests.

    The event chain is evidence of local attempted operations. Even a
    valid CLEAN marker cannot replace independent MQ object readbacks.
    """
    filename = path.name
    if not filename.endswith(".jsonl") or not _RUN.fullmatch(filename[:-6]):
        raise JournalError("Journal filename has unsafe fixture identity")
    begin = entries[0]
    if (begin["kind"] != "BEGIN"
            or begin["data"] != {"prefix": filename[:-6]}):
        raise JournalError("BEGIN must bind journal to its fixture prefix")
    pending = None
    unsuccessful = False
    for row in entries[1:]:
        kind, data = row["kind"], row["data"]
        if kind == "INTENT":
            if (pending is not None or set(data) != {"side", "operation"}
                    or data["side"] not in ("a", "b")
                    or data["operation"] not in _OPS):
                raise JournalError("Unexpected or overlapping CHLAUTH intent")
            pending = (data["side"], data["operation"])
        elif kind == "RESULT":
            if (pending is None
                    or set(data) != {"side", "operation", "status"}
                    or (data["side"], data["operation"]) != pending
                    or data["status"] not in _RESULT):
                raise JournalError("Unmatched CHLAUTH result")
            unsuccessful |= data["status"] != "ACKED"
            pending = None
        elif kind == "CLEAN":
            if (row is not entries[-1] or pending is not None
                    or unsuccessful
                    or data != {"verified_sides": {
                        "a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"
                    }}):
                raise JournalError("Invalid clean marker or unresolved operations")
        else:
            raise JournalError("Unknown CHLAUTH journal event")
    return pending


def read_journal(path):
    """Read and validate a previously created journal; no side effects."""
    return _read_events(Path(path))


def recovery_report(path):
    """Report possible residual mutations; NEVER authorize cleanup.

    Every attempted command remains a possible residual until live MQ
    readbacks independently prove absence. This report is local only.
    """
    entries = read_journal(path)
    attempts = []
    pending = None
    for row in entries[1:]:
        data = row["data"]
        if row["kind"] == "INTENT":
            pending = {"side": data["side"], "operation": data["operation"],
                       "status": "NO_RESULT"}
            attempts.append(pending)
        elif row["kind"] == "RESULT":
            pending["status"] = data["status"]
            pending = None
    complete = entries[-1]["kind"] == "CLEAN"
    return {
        "fixture": entries[0]["data"]["prefix"],
        "state": "CLEAN_RECORDED" if complete else "MANUAL_REVIEW_REQUIRED",
        "has_unanswered_intent": pending is not None,
        "attempts": attempts,
        "possible_residual_sides": [] if complete else sorted(
            {item["side"] for item in attempts}
        ),
        "can_auto_cleanup": False,
        "can_authorize_live_apply": False,
        "requires_independent_mq_readback": True,
    }


class LockedFixtureJournal:
    """Hold cooperative lock and record intent BEFORE attempting MQSC writes.

    A future runtime caller must independently prove complete MQ cleanup
    before invoking mark_clean. An interrupted INTENT remains unresolved.
    """

    def __init__(self, root, prefix):
        if not isinstance(prefix, str) or not _RUN.fullmatch(prefix):
            raise JournalError("Unsafe transient fixture prefix")
        self.root_arg = root
        self.prefix = prefix
        self.root = None
        self._lock = None
        self._log = None
        self._seq = 0
        self._previous = "0" * 64
        self._pending = set()
        self._has_failure = False
        self._finished = False
        self.path = None

    def __enter__(self):
        self.root = _safe_directory(self.root_arg)
        lockpath = self.root / ".fixture.lock"
        fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | _NOFOLLOW, 0o600)
        self._lock = fd
        try:
            mode = os.fstat(fd)
            if (not stat.S_ISREG(mode.st_mode)
                    or stat.S_IMODE(mode.st_mode) != 0o600
                    or mode.st_uid != os.geteuid()):
                raise JournalError("Unsafe journal lock file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise JournalError("Another CHLAUTH journal session is active") from exc
            for existing in sorted(self.root.glob("*.jsonl")):
                entries = _read_events(existing)
                if entries[-1]["kind"] != "CLEAN":
                    raise JournalError(
                        "Unresolved CHLAUTH journal; manual verification required: "
                        + existing.name
                    )
            self.path = self.root / (self.prefix + ".jsonl")
            self._log = os.open(
                self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
                0o600,
            )
            self._fsync_directory()
            self._append("BEGIN", {"prefix": self.prefix})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _fsync_directory(self):
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _append(self, kind, data):
        if self._log is None or self._finished:
            raise JournalError("Journal not active")
        self._seq += 1
        entry = {
            "seq": self._seq, "prev": self._previous,
            "kind": kind, "data": data,
        }
        encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
        entry["digest"] = hashlib.sha256(encoded).hexdigest()
        payload = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        cursor = 0
        while cursor < len(payload):
            length = os.write(self._log, payload[cursor:])
            if length <= 0:
                raise JournalError("Journal write incomplete")
            cursor += length
        os.fsync(self._log)
        self._previous = entry["digest"]

    def intent(self, side, operation):
        if side not in ("a", "b") or operation not in _OPS:
            raise JournalError("Unapproved CHLAUTH intent")
        if self._pending:
            raise JournalError("Resolve previous intent before proceeding")
        self._append("INTENT", {"side": side, "operation": operation})
        self._pending.add((side, operation))

    def result(self, side, operation, status):
        if status not in _RESULT or (side, operation) not in self._pending:
            raise JournalError("Unexpected CHLAUTH result without matching intent")
        self._append("RESULT", {
            "side": side, "operation": operation, "status": status,
        })
        self._pending.remove((side, operation))
        if status != "ACKED":
            self._has_failure = True

    def mark_clean(self, verified_sides):
        if self._pending or self._has_failure:
            raise JournalError("Unresolved or unsuccessful intent; cannot mark clean")
        if (not isinstance(verified_sides, dict)
                or verified_sides != {"a": "VERIFIED_CLEAN",
                                      "b": "VERIFIED_CLEAN"}):
            raise JournalError("Both independent MQ clean readbacks required")
        self._append("CLEAN", {"verified_sides": verified_sides})
        self._finished = True

    def __exit__(self, _type, _value, _traceback):
        if self._log is not None:
            os.close(self._log)
            self._log = None
        if self._lock is not None:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
            os.close(self._lock)
            self._lock = None
        return False
