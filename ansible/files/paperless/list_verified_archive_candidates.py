#!/usr/bin/env python3
"""Controller-side READ-ONLY list of currently eligible v1 archive dry-run names.

Inputs must come directly from the independently live NAS sender/source audit
(under sync.lock) and the live Paperless IMPORTED/owner/ACL exporter.
Reuse the existing single-file selector for EVERY match. A listed name is
NOT commit authorization: evidence may become stale immediately, and final
same-subvolume checks/commit gates are a separate manual process.

No NAS/LXC access; no file writes; never print hashes or receipt metadata.
"""
import json
import sys

import select_one_verified_archive_move as selector

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 10000


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("DUPLICATE_BUNDLE_KEY")
        result[name] = value
    return result


def candidates(nas, paperless):
    """Fail closed on malformed inventory; exclude unimported v1 sources."""
    sent = selector.parse_jsonl(
        nas, ("sender_receipt", "scope", "source", "receiver_source", "sha256"))
    # Even without matching sources, reject structurally malformed receipts.
    live = selector.parse_jsonl(
        paperless, ("schema_version", "bridge_receipt",
                    "receiver_source", "sha256", "document_id"))
    if len(sent) > MAX_CANDIDATES or len(live) > MAX_CANDIDATES:
        raise RuntimeError("CANDIDATE_INVENTORY_LIMIT")

    # Reuse the *exact* selection contract, including global duplicate,
    # schema, receipt identity, scope, checksum and document-ID checks.
    names = []
    for item in sent:
        if not isinstance(item["scope"], str) or not isinstance(item["source"], str):
            raise RuntimeError("INVALID_SOURCE_IDENTITY")
        only = item["scope"] + "/" + item["source"]
        try:
            selector.select_one(nas, paperless, only)
        except RuntimeError as exc:
            if str(exc) == "LIVE_IMPORT_NOT_MATCHED":
                continue
            raise
        names.append(only)

    # The selector validates whole inventories only if at least one sender
    # exists; empty NAS source inventory must be reported as zero candidates,
    # never interpreted as evidence of an import.
    if len(set(names)) != len(names):
        raise RuntimeError("DUPLICATE_MATCHED_SOURCE")
    return sorted(names)


def report(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"nas", "paperless"}:
        raise ValueError("INVALID_CANDIDATE_BUNDLE")
    names = candidates(bundle["nas"], bundle["paperless"])
    # JSON string quoting also escapes terminal control characters and
    # makes whitespace/unicode filenames unambiguous to copy.
    return (["V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES " + str(len(names))]
            + ["CANDIDATE " + json.dumps(name, ensure_ascii=True)
               for name in names]
            + ["CANDIDATE_AUDIT_COMPLETE", "NO_FILES_CHANGED",
               "ARCHIVE_NOT_AUTHORIZED", "PURGE_NOT_AUTHORIZED"])


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise RuntimeError("INVALID_BUNDLE_SIZE")
    bundle = json.loads(raw, object_pairs_hook=_unique)
    for line in report(bundle):
        print(line)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TypeError, KeyError, UnicodeError) as exc:
        # Never disclose source/receipt names or raw private evidence on
        # failure; Ansible also suppresses source/export/join task logs.
        allowed = {
            "INVALID_BUNDLE_SIZE", "DUPLICATE_BUNDLE_KEY",
            "INVALID_CANDIDATE_BUNDLE", "CANDIDATE_INVENTORY_LIMIT",
            "INVALID_SOURCE_IDENTITY", "DUPLICATE_MATCHED_SOURCE",
            "INVALID_ARCHIVE_SOURCE_EVIDENCE", "INVALID_ARCHIVE_EVIDENCE_RECORD",
            "ARCHIVE_EVIDENCE_LIMIT", "DUPLICATE_EVIDENCE_KEY",
            "INVALID_EXACT_ARCHIVE_SELECTION",
            "INVALID_NAS_ARCHIVE_INVENTORY",
            "INVALID_LIVE_IMPORT_INVENTORY",
            "EXACT_SENDER_RECEIPT_NOT_FOUND",
        }
        reason = str(exc)
        print("ARCHIVE_CANDIDATE_LIST_BLOCKED",
              reason if reason in allowed else "INVALID_OR_UNTRUSTED_EVIDENCE",
              file=sys.stderr)
        sys.exit(1)
