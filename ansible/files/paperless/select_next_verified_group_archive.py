#!/usr/bin/env python3
"""Select one *already live-import-verified* v1 group PDF, or report idle.

This is a pure, read-only adapter for the existing group single-PDF commit.
It MUST consume only the fresh stdout of
list_verified_lifecycle_archive_candidates.py, whose caller has already
validated ALL original, archived, deletion and Paperless live ACL evidence.
It does not create a release gate, transfer anything or claim v2 readiness.
"""
import json
import re
import sys

REPORT_HEAD = re.compile(r"V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES ([0-9]{1,5})\Z")
NAME = re.compile(r"(Eltern|Familie|Privat/(?:thomas|nadja))/[^/\\\x00]+[.]pdf\Z")
TAIL = (
    "CANDIDATE_AUDIT_COMPLETE",
    "NO_FILES_CHANGED",
    "ARCHIVE_NOT_AUTHORIZED",
    "PURGE_NOT_AUTHORIZED",
)
MAX_BYTES = 1024 * 1024


def choose(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("INVALID_FRESH_CANDIDATE_REPORT")
    rows = raw.splitlines()
    if len(rows) < 6:
        raise ValueError("MISSING_CANDIDATE_EVIDENCE")
    head = REPORT_HEAD.fullmatch(rows[0])
    if head is None or rows[1] != "DELETED_BY_USER_EXCLUDED 2":
        raise ValueError("INVALID_CANDIDATE_HEADER")
    count = int(head.group(1))
    if count > 10000 or len(rows) != count + 6 or tuple(rows[-4:]) != TAIL:
        raise ValueError("INCOMPLETE_CANDIDATE_INVENTORY")
    names = []
    for row in rows[2:-4]:
        if not row.startswith("CANDIDATE "):
            raise ValueError("UNEXPECTED_CANDIDATE_RECORD")
        payload = row[len("CANDIDATE "):]
        try:
            name = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("INVALID_CANDIDATE_JSON") from exc
        if (not isinstance(name, str) or not NAME.fullmatch(name)
                or json.dumps(name, ensure_ascii=True) != payload
                or name.split("/")[-1].startswith(".")):
            raise ValueError("INVALID_CANDIDATE_NAME")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("DUPLICATE_VERIFIED_SOURCE")
    group = [n for n in names if n.startswith(("Eltern/", "Familie/"))]
    # Pick one and let the existing one-shot runner recompute ALL proof
    # and audit the complete NAS/Paperless lifecycle before and after.
    return {"schema_version": 1, "only": group[0] if group else None,
            "groups_ready": len(group), "private_untouched": count - len(group),
            "status": "READY" if group else "IDLE"}


def main():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("INVALID_REPORT_INPUT_SIZE")
    result = choose(raw.decode("utf-8"))
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, UnicodeError, TypeError):
        print("GROUP_ARCHIVE_SELECTION_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
