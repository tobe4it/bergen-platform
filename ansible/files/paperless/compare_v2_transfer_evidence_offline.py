#!/usr/bin/env python3
"""OFFLINE ONLY: correlate v2 PREPARED, rsync result and receiver audit.

All evidence arguments are caller supplied. This module does NOT authenticate
the process or host that produced them, does NOT write journal events, and
MUST NOT be used to authorize SENT, transfer, import, archive or deletion.
A future trusted orchestrator must collect authenticated evidence itself.
"""
import hashlib
import re

from synology_receipt_v2_store import prepared_record

RSYNC_SENT = re.compile(
    r"sent [0-9][0-9,.]* bytes  received [0-9][0-9,.]* bytes  "
    r"[0-9][0-9,.]* bytes/sec\Z"
)
RSYNC_TOTAL = re.compile(
    r"total size is [0-9][0-9,.]*  speedup is [0-9][0-9,.]*\Z"
)
HASH = re.compile(r"[a-f0-9]{64}\Z")
SIZE = re.compile(r"[1-9][0-9]{0,9}\Z")
AUDIT_FIXED = frozenset({
    "RECEIVER_POINT_IN_TIME_VERIFIED",
    "NEW_FILE_NOT_ATTESTED",
    "PAPERLESS_IMPORT_NOT_ATTESTED",
    "SENT_NOT_AUTHORIZED",
    "SOURCE_DELETE_NOT_AUTHORIZED",
    "NO_FILES_CHANGED",
})


def _source_prepared(prepared):
    if not isinstance(prepared, dict):
        raise ValueError("INVALID_PREPARED")
    try:
        expected = prepared_record(prepared["scope"], prepared["source"],
                                   prepared["sha256"], prepared["signature"],
                                   prepared["incarnation_nonce"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("INVALID_PREPARED") from exc
    if prepared != expected or prepared.get("status") != "PREPARED":
        raise ValueError("INVALID_PREPARED")
    return expected


def _receiver_binding(prepared):
    scope, receiver_name = prepared["destination"].rsplit("/", 1)
    # Size bound by immutable NAS signature and receiver verifier argument.
    size = prepared["signature"][2]
    raw = scope + "\0" + receiver_name + "\0" + prepared["sha256"] + "\0" + str(size)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rsync_new_file(stdout, basename):
    if not isinstance(stdout, str) or len(stdout) > 16384 or "\r" in stdout or "\0" in stdout:
        raise ValueError("INVALID_RSYNC_OUTPUT")
    wanted = "<f+++++++++ " + basename
    lines = stdout.split("\n")
    if lines.count(wanted) != 1:
        raise ValueError("RSYNC_NEW_FILE_MARKER_MISSING_OR_AMBIGUOUS")
    for line in lines:
        if line in ("", "sending incremental file list", wanted):
            continue
        if RSYNC_SENT.fullmatch(line) or RSYNC_TOTAL.fullmatch(line):
            continue
        raise ValueError("RSYNC_UNEXPECTED_OUTPUT")


def _receiver_success(stdout, prepared):
    if not isinstance(stdout, str) or len(stdout) > 4096 or "\0" in stdout or "\r" in stdout:
        raise ValueError("INVALID_RECEIVER_OUTPUT")
    lines = stdout.splitlines()
    if len(lines) != len(AUDIT_FIXED) + 3 or len(set(lines)) != len(lines):
        raise ValueError("INCOMPLETE_OR_REPEATED_RECEIVER_PROOF")
    fields = {}
    fixed = set()
    for line in lines:
        if line in AUDIT_FIXED:
            fixed.add(line)
            continue
        key, space, value = line.partition(" ")
        if not space or key not in ("RECEIVER_BINDING", "RECEIVER_SHA256", "RECEIVER_BYTES"):
            raise ValueError("UNKNOWN_RECEIVER_PROOF_LINE")
        if key in fields:
            raise ValueError("DUPLICATE_RECEIVER_PROOF_FIELD")
        fields[key] = value
    if fixed != AUDIT_FIXED or set(fields) != {
            "RECEIVER_BINDING", "RECEIVER_SHA256", "RECEIVER_BYTES"}:
        raise ValueError("MISSING_RECEIVER_PROOF_FIELDS")
    if (not HASH.fullmatch(fields["RECEIVER_BINDING"])
            or not HASH.fullmatch(fields["RECEIVER_SHA256"])
            or not SIZE.fullmatch(fields["RECEIVER_BYTES"])
            or fields["RECEIVER_BINDING"] != _receiver_binding(prepared)
            or fields["RECEIVER_SHA256"] != prepared["sha256"]
            or int(fields["RECEIVER_BYTES"]) != prepared["signature"][2]):
        raise ValueError("RECEIVER_PROOF_IDENTITY_OR_DIGEST_MISMATCH")


def compare_offline(prepared, rsync_returncode, rsync_stdout,
                    rsync_stderr, receiver_returncode, receiver_stdout):
    """Validate structure of *supplied* evidence, without authorizing action.

    Neither subprocess stdout nor these parameters authenticate their origin.
    A matching file observed later might have pre-existed; only trusted
    orchestration can combine a new-file transport signal with independent
    point-in-time receiver proof. Even a successful comparison is NOT SENT.
    """
    record = _source_prepared(prepared)
    if type(rsync_returncode) is not int or rsync_returncode != 0:
        raise ValueError("RSYNC_PROCESS_UNSUCCESSFUL")
    if type(receiver_returncode) is not int or receiver_returncode != 0:
        raise ValueError("RECEIVER_PROCESS_UNSUCCESSFUL")
    if not isinstance(rsync_stderr, str) or rsync_stderr != "":
        raise ValueError("RSYNC_STDERR_NOT_EMPTY")
    _rsync_new_file(rsync_stdout, record["destination"].rsplit("/", 1)[1])
    _receiver_success(receiver_stdout, record)
    return {
        "receipt_id": record["receipt_id"],
        "receiver_source": record["destination"],
        "receiver_sha256": record["sha256"],
        "receiver_bytes": record["signature"][2],
        "rsync_new_file_marker_observed": True,
        "receiver_point_in_time_observed": True,
        "origin_authenticated": False,
        "durable_prepared_reverified_under_lock": False,
        "sent_authorized": False,
        "source_delete_authorized": False,
    }


__all__ = ["compare_offline"]
