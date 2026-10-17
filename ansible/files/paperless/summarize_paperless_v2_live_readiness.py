#!/usr/bin/env python3
"""Summarize TWO independently authenticated read-only v2 audit streams.

Only the orchestrating Ansible playbook authenticates their origin. This
module validates the framing and emits bounded anonymous counts. It NEVER
joins or authorizes an archive operation, even if matching counts are found.
It reads JSON from stdin; no NAS or Paperless connectivity and no writes.
"""
import json
import re
import sys

SCOPES = frozenset(("Familie", "Eltern", "Privat/thomas", "Privat/nadja"))
COUNT_ROW = re.compile(
    r"SCOPE (Familie|Eltern|Privat/thomas|Privat/nadja) "
    r"V1_SENT ([0-9]{1,6}) V1_PREPARED ([0-9]{1,6}) "
    r"V2_PREPARED ([0-9]{1,6}) V2_ATTEMPTED ([0-9]{1,6}) "
    r"V2_SENT ([0-9]{1,6})\Z"
)
INTEGER_ROW = re.compile(
    r"(TOTAL_JOURNAL_EVENTS|TOTAL_V1_SENT|UNRESOLVED_JOURNAL_EVENTS) "
    r"([0-9]{1,7})\Z"
)
BRIDGE = re.compile(r"[0-9a-f]{24}\.json\Z")
V2_ID = re.compile(r"v2-[0-9a-f]{32}-[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_STREAM = 2_000_000
MAX_RECORDS = 10000


def reject(reason):
    raise RuntimeError(reason)


def strict_pairs(pairs):
    output = {}
    for name, value in pairs:
        if name in output:
            reject("DUPLICATE_JSON_KEY")
        output[name] = value
    return output


def _lines(value):
    if not isinstance(value, str) or not 0 < len(value) <= MAX_STREAM:
        reject("INVALID_STREAM_SIZE")
    if "\r" in value or "\x00" in value:
        reject("INVALID_STREAM_CONTROL")
    return value.splitlines()


def check_nas(raw):
    rows = {}
    totals = {}
    required = {"HISTORY_AUDIT_COMPLETE", "ARCHIVE_NOT_AUTHORIZED", "NO_FILES_CHANGED"}
    markers = set()
    for line in _lines(raw):
        m = COUNT_ROW.fullmatch(line)
        if m is not None:
            scope = m.group(1)
            if scope in rows:
                reject("DUPLICATE_NAS_SCOPE")
            stats = tuple(int(v) for v in m.groups()[1:])
            if stats[4] > stats[3] or stats[3] > stats[2]:
                reject("INCONSISTENT_V2_EVENT_STAGES")
            rows[scope] = stats
            continue
        m = INTEGER_ROW.fullmatch(line)
        if m is not None:
            if m.group(1) in totals:
                reject("DUPLICATE_NAS_TOTAL")
            totals[m.group(1)] = int(m.group(2))
            continue
        if line in required and line not in markers:
            markers.add(line)
            continue
        reject("UNEXPECTED_NAS_OUTPUT")
    if set(rows) != SCOPES or markers != required or set(totals) != {
            "TOTAL_JOURNAL_EVENTS", "TOTAL_V1_SENT", "UNRESOLVED_JOURNAL_EVENTS"}:
        reject("INCOMPLETE_NAS_AUDIT")
    event_total = sum(sum(x) for x in rows.values())
    v1_sent = sum(x[0] for x in rows.values())
    unresolved = sum(x[1] + x[2] - x[4] for x in rows.values())
    if (totals["TOTAL_JOURNAL_EVENTS"] != event_total
            or totals["TOTAL_V1_SENT"] != v1_sent
            or totals["UNRESOLVED_JOURNAL_EVENTS"] != unresolved):
        reject("NAS_TOTAL_MISMATCH")
    return {"v1_sent": v1_sent, "v2_sent": sum(x[4] for x in rows.values()),
            "v2_prepared": sum(x[2] for x in rows.values()),
            "v2_attempted": sum(x[3] for x in rows.values()),
            "unresolved": unresolved}


def check_paperless(raw):
    lines = _lines(raw)
    markers = ["V2_LIVE_IMPORT_AUDIT_COMPLETE", "ARCHIVE_NOT_AUTHORIZED",
               "SOURCE_DELETE_NOT_AUTHORIZED", "NO_FILES_CHANGED"]
    if len(lines) < len(markers) or lines[-len(markers):] != markers:
        reject("INCOMPLETE_PAPERLESS_AUDIT")
    seen_ids, seen_bridges, seen_destinations = set(), set(), set()
    records = lines[:-len(markers)]
    if len(records) > MAX_RECORDS:
        reject("TOO_MANY_IMPORT_RECORDS")
    for line in records:
        if not line.startswith("{") or len(line) > 4096:
            reject("INVALID_PAPERLESS_RECORD_LINE")
        try:
            value = json.loads(line, object_pairs_hook=strict_pairs)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise RuntimeError("INVALID_PAPERLESS_RECORD_JSON") from exc
        if not isinstance(value, dict) or set(value) != {
                "schema_version", "status", "bridge_receipt", "receiver_source",
                "receipt_id", "sha256", "document_id"}:
            reject("INVALID_PAPERLESS_RECORD_SCHEMA")
        if (type(value["schema_version"]) is not int or value["schema_version"] != 2
                or value["status"] != "IMPORTED"
                or not isinstance(value["bridge_receipt"], str)
                or not BRIDGE.fullmatch(value["bridge_receipt"])
                or not isinstance(value["receipt_id"], str)
                or not V2_ID.fullmatch(value["receipt_id"])
                or not isinstance(value["sha256"], str)
                or not SHA.fullmatch(value["sha256"])
                or type(value["document_id"]) is not int
                or value["document_id"] <= 0):
            reject("INVALID_PAPERLESS_RECORD_IDENTITY")
        destination = value["receiver_source"]
        if not isinstance(destination, str) or not any(
                destination == scope + "/nas-" + value["receipt_id"] + ".pdf"
                for scope in SCOPES):
            reject("INVALID_PAPERLESS_DESTINATION")
        if (value["receipt_id"] in seen_ids or value["bridge_receipt"] in seen_bridges
                or destination in seen_destinations):
            reject("DUPLICATE_PAPERLESS_IMPORT")
        seen_ids.add(value["receipt_id"])
        seen_bridges.add(value["bridge_receipt"])
        seen_destinations.add(destination)
    return len(records)


def summarize(payload):
    if not isinstance(payload, dict) or set(payload) != {"nas", "paperless"}:
        reject("INVALID_AUDIT_BUNDLE")
    nas = check_nas(payload["nas"])
    imported = check_paperless(payload["paperless"])
    # A count is never an identity join or a fresh source-content check.
    return [
        "V1_SENT_COUNT " + str(nas["v1_sent"]),
        "V2_PREPARED_COUNT " + str(nas["v2_prepared"]),
        "V2_ATTEMPTED_COUNT " + str(nas["v2_attempted"]),
        "V2_SENT_COUNT " + str(nas["v2_sent"]),
        "V2_LIVE_IMPORTED_COUNT " + str(imported),
        "UNRESOLVED_SENDER_EVENTS " + str(nas["unresolved"]),
        "V2_EXACT_RECEIPT_JOIN_NOT_YET_VERIFIED",
        "V2_READONLY_PREFLIGHT_COMPLETE",
        "NO_FILES_CHANGED",
        "ARCHIVE_NOT_AUTHORIZED",
        "SOURCE_DELETE_NOT_AUTHORIZED",
        "PURGE_NOT_AUTHORIZED",
    ]


def main():
    data = sys.stdin.buffer.read(4_000_001)
    if not 0 < len(data) <= 4_000_000:
        reject("INVALID_BUNDLE_SIZE")
    content = json.loads(data, object_pairs_hook=strict_pairs)
    for line in summarize(content):
        print(line)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TypeError, UnicodeError) as exc:
        # No private source names, receipt IDs or confidential hashes in logs.
        reason = str(exc)
        if reason not in {
            "DUPLICATE_JSON_KEY", "INVALID_STREAM_SIZE", "INVALID_STREAM_CONTROL",
            "DUPLICATE_NAS_SCOPE", "INCONSISTENT_V2_EVENT_STAGES",
            "DUPLICATE_NAS_TOTAL", "UNEXPECTED_NAS_OUTPUT", "INCOMPLETE_NAS_AUDIT",
            "NAS_TOTAL_MISMATCH", "INCOMPLETE_PAPERLESS_AUDIT", "TOO_MANY_IMPORT_RECORDS",
            "INVALID_PAPERLESS_RECORD_LINE", "INVALID_PAPERLESS_RECORD_JSON",
            "INVALID_PAPERLESS_RECORD_SCHEMA", "INVALID_PAPERLESS_RECORD_IDENTITY",
            "INVALID_PAPERLESS_DESTINATION", "DUPLICATE_PAPERLESS_IMPORT",
            "INVALID_AUDIT_BUNDLE", "INVALID_BUNDLE_SIZE",
        }:
            reason = "UNKNOWN_AUDIT_FAILURE"
        print("V2_READONLY_PREFLIGHT_BLOCKED", reason, file=sys.stderr)
        sys.exit(1)
