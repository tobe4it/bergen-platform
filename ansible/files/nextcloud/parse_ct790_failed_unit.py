#!/usr/bin/env python3
"""Strictly parse one bounded failed systemd unit record from CT790.

Reads stdin only; no files, network, subprocesses or writes. Fail closed for
unexpected output, multiple failed units or missing systemd failure state.
"""
import json
import re
import sys

MAX_BYTES = 8192
UNIT_RE = r"[A-Za-z0-9_.@:-]{1,160}\.(?:service|socket|timer|target|mount|automount|swap|path|device|scope|slice)"
RECORD = re.compile(
    rf"^(?:●\s+)?(?P<unit>{UNIT_RE})\s+(?P<load>\S+)\s+"
    r"failed\s+(?P<sub>\S+)(?:\s+.*)?$"
)

def parse_failed_unit(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("OUTPUT_TOO_LARGE")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("INVALID_ENCODING") from exc
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 1:
        raise ValueError("EXPECTED_EXACTLY_ONE_FAILED_UNIT")
    match = RECORD.fullmatch(lines[0])
    if not match or match.group("load") not in ("loaded", "not-found", "masked"):
        raise ValueError("FAILED_UNIT_RECORD_UNRECOGNIZED")
    return {
        "result": "ROCKY_9_8_CT790_SINGLE_FAILED_UNIT_PARSED",
        "unit": match.group("unit"),
        "failed_unit_count": 1,
        "writes": 0,
    }

def main():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        result = parse_failed_unit(raw)
    except ValueError as exc:
        result = {
            "result": "ROCKY_9_8_CT790_FAILED_UNIT_PARSE_BLOCKED",
            "reason": str(exc),
            "writes": 0,
        }
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(1)
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
