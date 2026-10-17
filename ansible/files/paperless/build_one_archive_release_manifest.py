#!/usr/bin/env python3
"""Pure builder for an *operator-approved* exact-one-PDF NAS release manifest.

OFFLINE ONLY. No CLI, no files, no NAS access and no commit invocation.
Use only after a NEW independently live-verified two-deletion lifecycle,
a successful same-PDF non-committing preview, an effective DSM ACL check and
a separate explicit human approval. Never publish a generated manifest in logs.
"""
import hashlib
import json
import re

SITES = {"Familie": "paperless-scan", "Eltern": "paperless-scan",
         "Privat/thomas": "homes", "Privat/nadja": "homes"}
BRIDGE = re.compile(r"[a-f0-9]{24}[.]json\Z")
SENDER = re.compile(r"[a-f0-9]{64}[.]json\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


def build_manifest(scope_and_filename, proof, timestamp):
    if not isinstance(scope_and_filename, str) or not isinstance(proof, dict):
        raise ValueError("INVALID_ARCHIVE_APPROVAL_INPUT")
    scope, sep, filename = scope_and_filename.rpartition("/")
    if scope not in SITES or not sep or not filename or filename.startswith("."):
        raise ValueError("INVALID_ARCHIVE_APPROVAL_SCOPE")
    if ("/" in filename or "\\" in filename or "\x00" in filename
            or filename in (".", "..") or not filename.lower().endswith(".pdf")
            or len(filename.encode("utf-8")) > 255):
        raise ValueError("INVALID_ARCHIVE_APPROVAL_SOURCE")
    if set(proof) != {"schema_version", "sender_receipt", "bridge_receipt",
                      "receiver_source", "sha256", "document_id"}:
        raise ValueError("INVALID_ARCHIVE_APPROVAL_PROOF")
    digest = proof["sha256"]
    if (type(proof["schema_version"]) is not int or proof["schema_version"] != 1
            or not isinstance(digest, str) or not SHA.fullmatch(digest)
            or not isinstance(proof["sender_receipt"], str)
            or not SENDER.fullmatch(proof["sender_receipt"])
            or not isinstance(proof["bridge_receipt"], str)
            or not BRIDGE.fullmatch(proof["bridge_receipt"])
            or type(proof["document_id"]) is not int
            or proof["document_id"] <= 0
            or not isinstance(proof["receiver_source"], str)
            or not proof["receiver_source"].startswith(scope + "/")
            or not proof["receiver_source"].endswith("--nas-" + digest + ".pdf")
            or proof["sender_receipt"] != hashlib.sha256(
                (scope + "\0" + filename).encode("utf-8")).hexdigest() + ".json"):
        raise ValueError("APPROVAL_PROOF_NOT_BOUND_TO_SOURCE")
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("INVALID_ARCHIVE_APPROVAL_TIME")
    return {
        "schema_version": 1,
        "release": "one_original_pdf",
        "site": SITES[scope],
        "scope": scope,
        "source": filename,
        "sender_receipt": proof["sender_receipt"],
        "bridge_receipt": proof["bridge_receipt"],
        "sha256": digest,
        "document_id": proof["document_id"],
        "issued_at": timestamp,
        "expires_at": timestamp + 600,
    }


def canonical_bytes(value):
    """Canonical form accepted by synology_same_volume_archive_move.py."""
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":"), sort_keys=True) + "\n").encode("ascii")


__all__ = ("build_manifest", "canonical_bytes")
