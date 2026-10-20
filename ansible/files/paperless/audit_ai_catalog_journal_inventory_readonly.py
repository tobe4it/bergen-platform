"""Read-only inventory of *operator-selected* Paperless AI catalogue journal IDs.

Called via Python in the existing Paperless Django container, with a JSON stdin
envelope and an explicit main() appended by the Ansible playbook.
Never reads or emits OCR content, filenames, titles, accounts or journal snapshots.
No inference, journal migration, writes, locks or database mutation.
"""
import json
import sqlite3
import stat
import sys
from pathlib import Path

FRAME = "BERGEN_PAPERLESS_CATALOG_JOURNAL_INVENTORY_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
MAX_IDS = 8
VALID_STATES = {"PROCESSING", "REQUIRES_REVIEW", "APPLIED", "ROLLED_BACK"}


def report(**values):
    print(FRAME + json.dumps(dict(
        AUDIT="READ_ONLY", CHANGED=False,
        MODEL_INFERENCE="NO", DOCUMENTS_CHANGED="NO", **values
    ), sort_keys=True), flush=True)


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {"protocol", "document_ids"}:
        return None
    if payload.get("protocol") != "catalog-journal-inventory-v1":
        return None
    ids = payload.get("document_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS:
        return None
    if not all(type(i) is int and i > 0 for i in ids) or len(set(ids)) != len(ids):
        return None
    return ids


def query_states(ids):
    if JOURNAL.parent.is_symlink() or JOURNAL.is_symlink():
        raise ValueError("UNSAFE_JOURNAL")
    s = JOURNAL.stat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError("JOURNAL_NOT_REGULAR")
    # mode=ro refuses journal creation; query_only adds a second write block.
    with sqlite3.connect("file:" + str(JOURNAL) + "?mode=ro",
                         uri=True, timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        sql = ("SELECT document_id,state FROM catalogue WHERE document_id IN ("
               + ",".join("?" for _ in ids) + ")")
        rows = db.execute(sql, ids).fetchall()
    state_by_id = {}
    for doc_id, state in rows:
        if type(doc_id) is not int or doc_id not in ids or state not in VALID_STATES:
            raise ValueError("UNVERIFIED_JOURNAL_ROW")
        if doc_id in state_by_id:
            raise ValueError("DUPLICATE_JOURNAL_ROW")
        state_by_id[doc_id] = state
    return [{"document_id": i, "state": state_by_id.get(i, "NOT_RECORDED")}
            for i in ids]


def main():
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            report(STATUS="INPUT_REJECTED")
            return
        ids = validate(json.loads(raw))
        if ids is None:
            report(STATUS="INPUT_REJECTED")
            return
        from paperless.version import __full_version_str__
        if __full_version_str__ != "3.3.0":
            report(STATUS="VERSION_UNREVIEWED")
            return
        results = query_states(ids)
        report(STATUS="INSPECTED", SCOPED_COUNT=len(results),
               STATES=results)
    except Exception:
        # Do not disclose exception string, filesystem or database internals.
        report(STATUS="UNVERIFIED")


# The calling Ansible shell command appends an explicit main() call.
