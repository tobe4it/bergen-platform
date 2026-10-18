"""Compare two ephemeral sealed identity inventories without decoding identities.

This is an identity-link preflight ONLY, never permission to read documents.
"""
import json
import re
import sys


class Unsafe(Exception):
    pass


HEX = re.compile(r"^[0-9a-f]{64}$")


def checked(value):
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise Unsafe("Invalid fingerprint")
    return value


def rows(value, source):
    if not isinstance(value, dict) or value.get("AUDIT") != "READ_ONLY" or value.get("SYSTEM") != source:
        raise Unsafe("Malformed inventory")
    data = value.get("ACCOUNTS")
    if not isinstance(data, list) or len(data) > 1000 or value.get("COUNT") != len(data):
        raise Unsafe("Invalid account count")
    seen = set()
    for row in data:
        if not isinstance(row, dict):
            raise Unsafe("Bad row")
        email = checked(row.get("email"))
        if email in seen:
            raise Unsafe("Ambiguous email")
        seen.add(email)
        if source == "BERGEN_AI":
            checked(row.get("subject"))
            if row.get("role") not in ("ADMIN", "USER", "PENDING"):
                raise Unsafe("Bad role")
        else:
            if row.get("uid") is None and row.get("sub") is None:
                raise Unsafe("No identity")
            if row.get("uid") is not None:
                checked(row["uid"])
            if row.get("sub") is not None:
                checked(row["sub"])
            if type(row.get("active")) is not bool or type(row.get("staff")) is not bool:
                raise Unsafe("Bad state")
    return data


def compare(ai, paperless):
    ai_rows = rows(ai, "BERGEN_AI")
    p_rows = rows(paperless, "PAPERLESS")
    matched = 0
    inactive = 0
    subject_mismatch = 0
    email_drift = 0
    paperless_missing = 0
    unmatched_ai = 0
    for user in ai_rows:
        candidates = [
            p for p in p_rows
            if user["subject"] in (p["uid"], p["sub"])
        ]
        if len(candidates) > 1:
            raise Unsafe("Same subject maps to multiple paperless users")
        if candidates:
            p = candidates[0]
            if p["email"] != user["email"]:
                email_drift += 1
            elif not p["active"]:
                inactive += 1
            else:
                matched += 1
        else:
            unmatched_ai += 1
            if any(p["email"] == user["email"] for p in p_rows):
                subject_mismatch += 1
            else:
                paperless_missing += 1
    problems = unmatched_ai + inactive + email_drift
    return {
        "STATUS": "LINK_CANDIDATES_PRESENT" if matched and not problems else "REQUIRES_IDENTITY_REVIEW",
        "AUDIT": "READ_ONLY",
        "AI_OIDC_ACCOUNTS": len(ai_rows),
        "PAPERLESS_OIDC_ACCOUNTS": len(p_rows),
        "MATCHED_ACTIVE_EMAIL_AND_SUBJECT": matched,
        "PAPERLESS_LINK_MISSING": paperless_missing,
        "SUBJECT_MISMATCH_SAME_EMAIL": subject_mismatch,
        "INACTIVE_PAPERLESS_IDENTITY": inactive,
        "SUBJECT_MATCH_EMAIL_DRIFT": email_drift,
        "ISSUER_EQUALITY": "NOT_PROVEN",
        "LIVE_USER_DELEGATION": "NOT_PROVEN",
        "PAPERLESS_DOCUMENT_ACL": "NOT_PROVEN",
        "CHILD_ACCESS_SEPARATION": "NOT_PROVEN",
        "GROUP_CLAIM_VALIDITY": "NOT_PROVEN",
        "AUTOMATIC_GROUP_SYNC_SAFE": "NO",
        "CHANGED": False,
    }


def main():
    try:
        inp = json.load(sys.stdin)
        result = compare(inp["ai"], inp["paperless"])
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print('{"AUDIT":"FAILED_CLOSED","CHANGED":false}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
