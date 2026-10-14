#!/usr/bin/env python3
"""Gated, narrowly scoped document 15 journal publication inside LXC 126.

This script is never invoked by the read-only plan. The Ansible apply play
must require a separate explicit approval before invoking it. It runs as
paperless-ingest, loads the reviewed offline v2 schema/store source from
the controller via stdin, and publishes exactly one fixed event.

No source deletion, no Paperless API calls, no archive permission.
"""
import hashlib
import json
import os
import pwd
import sys
import types
from pathlib import Path

DIRECTORY = Path("/var/lib/paperless-ingest/deletion-decisions")
EXPECTED_UID = 997
EXPECTED_GID = 988
EXPECTED_EVENT = "2a6d73664436c1a3e0432d7a07911feab86ba2a617a185b81bc30580fdd67e90"
EXPECTED_RECORD_SHA = "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b"


def _load_module(name, source):
    if not isinstance(source, str) or not source.startswith("#!/usr/bin/env python3\n"):
        raise RuntimeError("UNEXPECTED_REVIEWED_SOURCE")
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name + ".py", "exec"), module.__dict__)
    return module


def main(request):
    if not isinstance(request, dict) or set(request) != {
        "nas", "deleted", "schema_source", "store_source", "plan_source"
    }:
        raise RuntimeError("INVALID_JOURNAL_PUBLICATION_REQUEST")
    user = pwd.getpwnam("paperless-ingest")
    if (os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_GID
            or user.pw_uid != EXPECTED_UID or user.pw_gid != EXPECTED_GID):
        raise RuntimeError("RESTRICTED_INGEST_IDENTITY_REQUIRED")

    schema = _load_module("deleted_by_user_decision_journal", request["schema_source"])
    store = _load_module("deleted_by_user_decision_store", request["store_source"])
    plan = _load_module("plan_deleted_by_user_journal_target", request["plan_source"])

    nas = schema.one(request["nas"], marker=True)
    deleted = schema.one(request["deleted"])
    record = schema.build(nas, deleted)
    payload = schema.canonical(record)
    if (record["event_id"] != EXPECTED_EVENT
            or hashlib.sha256(payload).hexdigest() != EXPECTED_RECORD_SHA):
        raise RuntimeError("UNEXPECTED_APPROVED_JOURNAL_IDENTITY")

    # Independent target validation pins the full canonical record and digest.
    if plan.validate(record) != payload:
        raise RuntimeError("INDEPENDENT_DOCUMENT_15_TARGET_MISMATCH")

    # Only the exact, separately approved document 15 event may be published.
    # This check includes the parent rootfs and expected ownership/modes.
    directory_fd = plan.check_directory(DIRECTORY)
    os.close(directory_fd)
    path, created = store.publish_once(DIRECTORY, record)

    # Verify the published bytes and security properties via the same
    # no-symlink, no-hardlink validation used for idempotent retries.
    fd = store._open_private_directory(DIRECTORY)
    try:
        store._existing_matches(fd, path.name, payload)
    finally:
        os.close(fd)
    print("JOURNAL_CREATED_AND_VERIFIED" if created else "JOURNAL_ALREADY_IDENTICAL_AND_VERIFIED")
    print("JOURNAL_FILENAME", path.name)
    print("JOURNAL_SHA256", hashlib.sha256(payload).hexdigest())
    print("NO_RECEIPTS_CHANGED")
    print("NO_REIMPORT_OR_RESTORE")
    print("NO_ARCHIVE_AUTHORIZATION")


if __name__ == "__main__":
    if sys.argv != [sys.argv[0], "--apply"]:
        raise SystemExit("EXPLICIT_APPLY_ARGUMENT_REQUIRED")
    main(json.load(sys.stdin))
