#!/usr/bin/env python3
"""Read-only listing ONLY after the complete, pinned 15/26 lifecycle audit.

Input: fresh registered NAS originals + Paperless lifecycle JSONL + the
successful lifecycle matcher output from audit-paperless-import-lifecycle-15-26.
Never turn stale DELETED_BY_USER bridge receipts into archive candidates.
Reuses the existing exact v1 single-source match contract. Does not access
hosts or modify any files. Output: JSON-escaped scope/original names only.
"""
import json
import sys

import list_verified_archive_candidates as candidate_list
import match_paperless_import_lifecycle_15_26 as lifecycle
import select_one_verified_archive_move as selector

MAX_INPUT_BYTES = 16 * 1024 * 1024


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_LIFECYCLE_FIELD")
        result[key] = value
    return result


def parse_lifecycle(raw):
    if not isinstance(raw, str) or len(raw) > 8 * 1024 * 1024:
        raise ValueError("INVALID_LIFECYCLE_EVIDENCE")
    imported, deleted, all_sources, all_bridges = [], {}, set(), set()
    for row in raw.splitlines():
        if not row.strip():
            continue
        if len(imported) + len(deleted) >= 10000:
            raise ValueError("LIFECYCLE_RECORD_LIMIT")
        item = json.loads(row, object_pairs_hook=strict_object)
        if not isinstance(item, dict) or item.get("schema_version") != 1 or type(item["schema_version"]) is not int:
            raise ValueError("INVALID_LIFECYCLE_SCHEMA")
        status = item.get("status")
        if status == "IMPORTED":
            if set(item) != {"schema_version", "status", "bridge_receipt",
                             "receiver_source", "sha256", "document_id"}:
                raise ValueError("INVALID_IMPORTED_LIFECYCLE_SCHEMA")
        elif status == "DELETED_BY_USER":
            if set(item) != {"schema_version", "status", "bridge_receipt",
                             "sender_receipt", "receiver_source", "sha256",
                             "document_id"}:
                raise ValueError("INVALID_DELETED_LIFECYCLE_SCHEMA")
            docid = item["document_id"]
            if type(docid) is not int or docid not in lifecycle.DELETIONS or docid in deleted:
                raise ValueError("UNAPPROVED_DELETED_LIFECYCLE")
            _, _, bridge, sender, original = lifecycle.DELETIONS[docid]
            expected = {"schema_version": 1, "status": "DELETED_BY_USER",
                        "bridge_receipt": bridge, "sender_receipt": sender,
                        "receiver_source": "Privat/thomas/" + original[:-4] +
                                           "--nas-" + lifecycle.SHA + ".pdf",
                        "sha256": lifecycle.SHA, "document_id": docid}
            if item != expected:
                raise ValueError("DELETED_LIFECYCLE_IDENTITY_CHANGED")
            deleted[docid] = item
        else:
            raise ValueError("UNKNOWN_LIFECYCLE_STATUS")

        source = item["receiver_source"]
        bridge = item["bridge_receipt"]
        if not isinstance(source, str) or not isinstance(bridge, str):
            raise ValueError("INVALID_LIFECYCLE_IDENTITY")
        if source in all_sources or bridge in all_bridges:
            raise ValueError("DUPLICATE_LIFECYCLE_IDENTITY")
        all_sources.add(source)
        all_bridges.add(bridge)
        if status == "IMPORTED":
            imported.append({key: value for key, value in item.items()
                             if key != "status"})

    if set(deleted) != set(lifecycle.DELETIONS):
        raise ValueError("MISSING_VERIFIED_DELETED_LIFECYCLE")
    return imported, deleted


def report(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"nas", "paperless_lifecycle", "lifecycle_report"}:
        raise ValueError("INVALID_LIFECYCLE_CANDIDATE_REQUEST")
    sent = selector.parse_jsonl(
        bundle["nas"], ("sender_receipt", "scope", "source", "receiver_source", "sha256"))
    imported, deleted = parse_lifecycle(bundle["paperless_lifecycle"])
    if not sent or len(sent) != len(imported):
        raise ValueError("LIFECYCLE_COUNTS_DO_NOT_MATCH")

    # The Ansible caller MUST have just run the full independent audited
    # journals+NAS absences+Paperless ACL matcher. Require all its markers.
    text = bundle["lifecycle_report"]
    if not isinstance(text, str) or len(text) > 1024 * 1024:
        raise ValueError("INVALID_LIFECYCLE_REPORT")
    lines = text.splitlines()
    required = {
        "PAPERLESS_LIVE_IMPORTED " + str(len(imported)),
        "NAS_SENT_VERIFIED " + str(len(sent)),
        "DELETED_BY_USER " + str(len(deleted)),
        "IMPORT_LIFECYCLE_RECONCILED",
        "ARCHIVE_NOT_AUTHORIZED",
        "NO_RECEIPTS_CHANGED",
        "NO_FILES_CHANGED",
    }
    if not required.issubset(set(lines)) or len(lines) != len(set(lines)):
        raise ValueError("LIFECYCLE_AUDIT_INCOMPLETE")

    live = "\n".join(json.dumps(item, sort_keys=True, ensure_ascii=True)
                     for item in imported)
    names = candidate_list.candidates(bundle["nas"], live)
    if len(names) != len(sent):
        raise ValueError("SOURCE_NOT_LIVE_IMPORTED")

    # All v1 originals matched; deleted imports explicitly remain excluded.
    return (["V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES " + str(len(names)),
             "DELETED_BY_USER_EXCLUDED " + str(len(deleted))]
            + ["CANDIDATE " + json.dumps(name, ensure_ascii=True)
               for name in names]
            + ["CANDIDATE_AUDIT_COMPLETE", "NO_FILES_CHANGED",
               "ARCHIVE_NOT_AUTHORIZED", "PURGE_NOT_AUTHORIZED"])


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise ValueError("INVALID_BUNDLE_SIZE")
    value = json.loads(raw, object_pairs_hook=strict_object)
    for line in report(value):
        print(line)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyError, TypeError, UnicodeError):
        # No private receiver, NAS filenames, digests or exception details.
        print("V1_LIFECYCLE_CANDIDATES_BLOCKED", file=sys.stderr)
        sys.exit(1)
