#!/usr/bin/env python3
"""Read-only live Paperless proof for ONLY imported group-scope NAS PDFs.

Run as root in unprivileged Paperless LXC via pct exec. The raw JSONL has
document identities and MUST stay in Ansible no_log. Never authorizes archiving.
Historical two intentionally deleted PRIVATE documents are out of scope.
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

RECONCILER = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
GROUPS = ("Familie", "Eltern")
SHA = re.compile(r"[0-9a-f]{64}\Z")
BRIDGE = re.compile(r"[0-9a-f]{24}\.json\Z")
MAX = 10000


def collect(mod):
    found = []
    seen = set()
    paths = sorted(mod.RECEIPTS.glob("*.json"))
    if len(paths) > MAX:
        raise RuntimeError("BRIDGE_LIMIT_EXCEEDED")
    for path in paths:
        receipt, filename, (owner, group) = mod.load_receipt(path)
        if receipt.get("status") != "IMPORTED":
            continue
        source = receipt.get("source")
        if not isinstance(source, str):
            raise RuntimeError("INVALID_RECEIVER_SOURCE")
        scope, sep, base = source.rpartition("/")
        if not sep or scope not in GROUPS:
            continue
        match = re.search(r"--nas-([0-9a-f]{64})\.pdf\Z", base)
        if match is None:
            continue
        sha = receipt.get("sha256")
        docid = receipt.get("document_id")
        if (not isinstance(sha, str) or not SHA.fullmatch(sha)
                or sha != match.group(1)
                or type(docid) is not int or docid <= 0
                or not BRIDGE.fullmatch(path.name)
                or source in seen):
            raise RuntimeError("INVALID_GROUP_BRIDGE_PROOF")
        seen.add(source)
        if mod.verify(filename, sha, owner, group) != docid:
            raise RuntimeError("LIVE_GROUP_IMPORT_NOT_VERIFIED")
        found.append({"receiver_source": source, "sha256": sha,
                      "document_id": docid, "bridge_receipt": path.name})
    return found


def main():
    if os.geteuid() != 0 or not RECONCILER.is_file() or RECONCILER.is_symlink():
        raise RuntimeError("RECONCILER_NOT_TRUSTED")
    spec = importlib.util.spec_from_file_location("reconcile_group_readonly", RECONCILER)
    if spec is None or spec.loader is None:
        raise RuntimeError("RECONCILER_NOT_LOADABLE")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for item in collect(mod):
        print(json.dumps(item, ensure_ascii=True, sort_keys=True))
    print("LIVE_GROUP_IMPORT_EVIDENCE_COMPLETE")
    print("NO_FILES_CHANGED")
    print("ARCHIVE_NOT_AUTHORIZED")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        print("LIVE_GROUP_IMPORT_EVIDENCE_BLOCKED", file=sys.stderr)
        sys.exit(1)
