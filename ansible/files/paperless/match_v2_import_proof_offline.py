#!/usr/bin/env python3
"""OFFLINE ONLY: match a complete v2 SENT receipt with live import proof.

The caller MUST separately authenticate the NAS under sender lock and
the fresh Paperless exporter process. Submitted dictionaries are untrusted.
Never approves archive, quarantine, user deletion, source unlink or purge.
"""
import re

import synology_receipt_v2_store as store

BRIDGE = re.compile(r"[0-9a-f]{24}\.json\Z")
V2 = re.compile(r"v2-[0-9a-f]{32}-[0-9a-f]{64}\Z")


def match_offline(sent, imported):
    """Compare exact filename-incarnation identity, not only shared SHA-256."""
    if not isinstance(sent, dict) or not isinstance(imported, dict):
        raise ValueError("IMPORT_PROOFS_REQUIRED")
    if store._validate(sent) != "SENT":
        raise ValueError("V2_SENT_EVENT_REQUIRED")
    required = {
        "schema_version", "status", "bridge_receipt", "receiver_source",
        "receipt_id", "sha256", "document_id",
    }
    if (set(imported) != required or type(imported["schema_version"]) is not int
            or imported["schema_version"] != 2 or imported["status"] != "IMPORTED"
            or not isinstance(imported["bridge_receipt"], str)
            or not BRIDGE.fullmatch(imported["bridge_receipt"])
            or not isinstance(imported["receipt_id"], str)
            or not V2.fullmatch(imported["receipt_id"])
            or type(imported["document_id"]) is not int or imported["document_id"] <= 0):
        raise ValueError("INVALID_V2_IMPORT_RECORD")
    if (imported["receipt_id"] != sent["receipt_id"]
            or imported["receiver_source"] != sent["destination"]
            or imported["sha256"] != sent["sha256"]):
        raise RuntimeError("V2_IMPORT_IDENTITY_MISMATCH")
    return {
        "receipt_id": sent["receipt_id"],
        "bridge_receipt": imported["bridge_receipt"],
        "document_id": imported["document_id"],
        "sha256": sent["sha256"],
        "receiver_source": sent["destination"],
        "identity_match": True,
        "origin_authenticated": False,
        "fresh_acl_verified_by_this_function": False,
        "archive_authorized": False,
        "source_delete_authorized": False,
    }


__all__ = ["match_offline"]
