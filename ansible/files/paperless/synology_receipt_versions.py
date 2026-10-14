#!/usr/bin/env python3
"""Pure v2 receipt identity and compatibility decisions for Synology scans.

Not wired into the active sender. No I/O or state changes. The future
archiver must establish durable ARCHIVED proof before a reused name is
allowed to start a new version after an existing legacy receipt.
"""
import hashlib
import json
import re
from pathlib import Path

SHA256 = re.compile(r"[a-f0-9]{64}\Z")
VALID_SCOPE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\Z")


def validate(scope, basename, sha256, signature):
    if (not isinstance(scope, str) or not VALID_SCOPE.fullmatch(scope)
            or any(p in ("", ".", "..") for p in scope.split("/"))):
        raise ValueError("INVALID_SCOPE")
    if (not isinstance(basename, str) or basename in ("", ".", "..")
            or "/" in basename or "\\" in basename or "\x00" in basename
            or not basename.lower().endswith(".pdf")
            or len(basename.encode("utf-8")) > 255):
        raise ValueError("INVALID_BASENAME")
    if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        raise ValueError("INVALID_SHA256")
    if (not isinstance(signature, (list, tuple)) or len(signature) != 5
            or any(type(n) is not int or n < 0 for n in signature)):
        raise ValueError("INVALID_SIGNATURE")


def legacy_id(scope, basename):
    # The historical key must remain byte-for-byte stable.
    if (not isinstance(scope, str) or not VALID_SCOPE.fullmatch(scope)
            or any(p in ("", ".", "..") for p in scope.split("/"))
            or not isinstance(basename, str) or basename in ("", ".", "..")
            or "/" in basename or "\\" in basename or "\x00" in basename):
        raise ValueError("INVALID_LEGACY_KEY")
    return hashlib.sha256((scope + "\0" + basename).encode("utf-8")).hexdigest()


def version_id(scope, basename, sha256, signature):
    """Bind content and NAS file incarnation; never reuse a v1 receipt key."""
    validate(scope, basename, sha256, signature)
    payload = ["bergen-paperless-receipt-v2", scope, basename, sha256, list(signature)]
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "v2-" + hashlib.sha256(canonical).hexdigest()


def receipt_filename(scope, basename, sha256, signature):
    return version_id(scope, basename, sha256, signature) + ".json"


def classify_existing(existing, scope, basename, sha256, signature, version):
    """Fail closed on any older unresolved or unarchived same-name version.

    existing: iterable of sender receipt dictionaries for this scope+basename,
    including legacy receipts. Caller must discover all matching receipts from
    the private state directory; absence cannot be assumed from one key lookup.
    This routine is a policy helper, not authorization to transfer.
    """
    validate(scope, basename, sha256, signature)
    same = []
    other = []
    for receipt in existing:
        if (not isinstance(receipt, dict) or receipt.get("scope") != scope
                or receipt.get("source") != basename):
            raise ValueError("UNEXPECTED_RECEIPT_IN_SET")
        status = receipt.get("status")
        if status not in ("PREPARED", "SENT"):
            raise ValueError("UNSAFE_RECEIPT_STATUS")
        if receipt.get("sha256") == sha256 and receipt.get("signature") == list(signature):
            same.append(receipt)
        else:
            other.append(receipt)
    if len(same) > 1:
        raise ValueError("DUPLICATE_VERSION_PROOFS")
    if same:
        if same[0]["status"] != "SENT":
            return "BLOCK_PREPARED"
        if other and any(x["status"] != "SENT" for x in other):
            return "BLOCK_PREVIOUS_PREPARED"
        return "TRACKED"
    if other:
        # No archived receipt contract is implemented yet; never silently
        # permit a new incarnation with a reused filename.
        return "BLOCK_NAME_REUSE_PENDING_ARCHIVE_PROOF"
    return "NEW_VERSION_READY"


__all__ = ["legacy_id", "version_id", "receipt_filename", "classify_existing"]
