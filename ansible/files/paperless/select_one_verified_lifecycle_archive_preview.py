#!/usr/bin/env python3
"""Exact ONE v1 archive preview proof, sourced from full 15/26 lifecycle only.

Requires independently verified and freshly acquired controller evidence from
audit-paperless-import-lifecycle-15-26.yml. NEVER authorizes a file move.
No host access, writes, archive operation, or release-gate manipulation.
The private JSON proof is for stdin of the separately disabled NAS worker.
"""
import json
import sys

import list_verified_lifecycle_archive_candidates as lifecycle_candidates
import select_one_verified_archive_move as selector

MAX_INPUT_BYTES = 16 * 1024 * 1024


def select(bundle):
    if not isinstance(bundle, dict) or set(bundle) not in (
            {"nas", "paperless_lifecycle", "lifecycle_report", "only"},
            {"nas", "paperless_lifecycle", "lifecycle_report", "only", "archived"}):
        raise ValueError("INVALID_PREVIEW_REQUEST")
    requested = bundle["only"]
    if not isinstance(requested, str):
        raise ValueError("INVALID_ARCHIVE_SELECTION")
    evidence = {key: bundle[key] for key in (
        "nas", "paperless_lifecycle", "lifecycle_report")}
    if "archived" in bundle:
        evidence["archived"] = bundle["archived"]
    # Complete private journal and full 1:1 live-import inventory validation
    # happens first. The Ansible caller must freshly run the independent
    # complete host+NAS lifecycle audit before handing this data to us.
    report = lifecycle_candidates.report(evidence)
    marker = "CANDIDATE " + json.dumps(requested, ensure_ascii=True)
    if marker not in report:
        raise RuntimeError("REQUEST_NOT_A_VERIFIED_LIVE_CANDIDATE")
    live, deleted = lifecycle_candidates.parse_lifecycle(bundle["paperless_lifecycle"])
    if len(deleted) != 2:
        raise RuntimeError("INCOMPLETE_DELETION_PROOFS")
    records = "\n".join(json.dumps(item, sort_keys=True, ensure_ascii=True)
                        for item in live)
    return selector.select_one(bundle["nas"], records, requested)


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise ValueError("INVALID_PREVIEW_REQUEST_SIZE")
    bundle = json.loads(raw, object_pairs_hook=lifecycle_candidates.strict_object)
    print(json.dumps(select(bundle), sort_keys=True,
                     ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyError, TypeError, UnicodeError):
        # Do not print names, receipt IDs or document IDs from private source.
        print("V1_ARCHIVE_PREVIEW_SELECTION_BLOCKED", file=sys.stderr)
        sys.exit(1)
