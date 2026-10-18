"""Compare two ephemeral sealed identity inventories without decoding identities.

This is an identity-link preflight ONLY, never permission to read documents.
"""
import json
import re
import sys


class Unsafe(Exception):
    pass


HEX = re.compile(r"^[0-9a-f]{64}$")


# The Paperless django-admin shell can emit initialization banners on stdout
# before the single sealed audit record. Never parse stdout as bare JSON.
PAPERLESS_FRAME = "BERGEN_PAPERLESS_OIDC_AUDIT_V1:"
PARSER_ERRORS = frozenset({
    "PAPERLESS_STDOUT_INVALID",
    "PAPERLESS_FRAME_MISSING",
    "PAPERLESS_FRAME_DUPLICATE",
    "PAPERLESS_FRAME_JSON_INVALID",
    "PAPERLESS_FRAME_SCHEMA_INVALID",
})


def parse_paperless_stdout(raw):
    if not isinstance(raw, str) or len(raw) > 300_000:
        raise Unsafe("PAPERLESS_STDOUT_INVALID")
    lines = [s.strip() for s in raw.splitlines() if s.strip()]
    if len(lines) > 40:
        raise Unsafe("PAPERLESS_STDOUT_INVALID")
    frames = [line[len(PAPERLESS_FRAME):] for line in lines
              if line.startswith(PAPERLESS_FRAME)]
    if not frames:
        raise Unsafe("PAPERLESS_FRAME_MISSING")
    if len(frames) != 1:
        raise Unsafe("PAPERLESS_FRAME_DUPLICATE")
    try:
        data = json.loads(frames[0])
    except (ValueError, TypeError):
        raise Unsafe("PAPERLESS_FRAME_JSON_INVALID") from None
    # Validate the canonical envelope before the existing per-account
    # fingerprint checks in compare(). A FAIL_CLOSED result is not accepted.
    if (not isinstance(data, dict)
        or data.get("AUDIT") != "READ_ONLY"
        or data.get("SYSTEM") != "PAPERLESS"):
        raise Unsafe("PAPERLESS_FRAME_SCHEMA_INVALID")
    return data, len(lines) - 1


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
        paperless, ignored_lines = parse_paperless_stdout(inp["paperless_stdout"])
        result = compare(inp["ai"], paperless)
        # Only the number of discarded shell status lines is reported, never
        # their contents. The untrusted text remains protected by no_log.
        result["PAPERLESS_SHELL_STATUS_LINES_SUPPRESSED"] = ignored_lines
        print(json.dumps(result, sort_keys=True))
    except Unsafe as err:
        code = str(err) if str(err) in PARSER_ERRORS else "IDENTITY_COMPARE_FAILED"
        print(json.dumps({"AUDIT": "FAILED_CLOSED", "CHANGED": False,
                          "CODE": code}, sort_keys=True))
        raise SystemExit(2)
    except Exception:
        print('{"AUDIT":"FAILED_CLOSED","CHANGED":false,"CODE":"COMPARE_INTERNAL_ERROR"}')
        raise SystemExit(2)


if __name__ == "__main__":
    main()
