#!/usr/bin/env python3
"""Prepare a private, independently reviewed ACL EXPECTATION matrix.

Never reads Paperless or the running AI system. It solicits two existing
non-privileged OIDC-linked Paperless account names and three or four document IDs;
expected access derives exclusively from the operator-confirmed category
(private A/optional private B/shared adult/shared family), NOT live grants.
Output: protected, git-ignored site-local file (0600), no overwrite.
"""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import re
import sys

ALLOWED_FILE = "paperless-ai-acl.local.yml"
USER_RE = re.compile(r"^[A-Za-z0-9_.@+-]{1,100}$")
SCOPE_RULES = {
    "balanced": (
        ("Privates Dokument des Kontos A", (True, False)),
        ("Privates Dokument des Kontos B", (False, True)),
        ("Gemeinsam freigegebenes Eltern-Dokument", (True, True)),
        ("Gemeinsam freigegebenes Familien-Dokument", (True, True)),
    ),
    # B has no private documents yet: deliberately weaker A-denial coverage.
    "no-private-b": (
        ("Privates Dokument des Kontos A", (True, False)),
        ("Gemeinsam freigegebenes Eltern-Dokument", (True, True)),
        ("Gemeinsam freigegebenes Familien-Dokument", (True, True)),
    ),
}


class InvalidMatrix(ValueError):
    pass


def build_cases(users, document_ids, profile="balanced"):
    if profile not in SCOPE_RULES:
        raise InvalidMatrix("INVALID_PROFILE")
    rules = SCOPE_RULES[profile]
    if (not isinstance(users, (list, tuple)) or len(users) != 2
        or any(not isinstance(u, str) or not USER_RE.fullmatch(u) for u in users)
        or users[0] == users[1]):
        raise InvalidMatrix("INVALID_IDENTITIES")
    if (not isinstance(document_ids, (list, tuple))
        or len(document_ids) != len(rules)
        or any(type(doc) is not int or doc <= 0 for doc in document_ids)
        or len(set(document_ids)) != len(rules)):
        raise InvalidMatrix("INVALID_DOCUMENT_IDS")
    return [
        {"username": user, "document_id": doc, "allow": allow}
        for doc, (_, expectations) in zip(document_ids, rules)
        for user, allow in zip(users, expectations)
    ]


def render_matrix(cases, profile="balanced"):
    if profile not in SCOPE_RULES or not isinstance(cases, list) or len(cases) != 2 * len(SCOPE_RULES[profile]):
        raise InvalidMatrix("INVALID_CASE_COUNT")
    lines = [
        "---",
        "# Private owner-reviewed expected ACL policy. NO imported live grants.",
        "# Exactly two actual non-staff OIDC-linked Paperless users.",
        "# Independently classified existing Paperless documents.",
        "# no-private-b is a limited read-only diagnostic, NOT full denial coverage.",
        "paperless_oidc_acl_audit_approved: true",
        "paperless_oidc_acl_profile: " + profile,
        "paperless_oidc_acl_expected_cases:",
    ]
    for entry in cases:
        if (not isinstance(entry, dict)
            or set(entry) != {"username", "document_id", "allow"}
            or not isinstance(entry["username"], str)
            or not USER_RE.fullmatch(entry["username"])
            or type(entry["document_id"]) is not int
            or entry["document_id"] <= 0
            or type(entry["allow"]) is not bool):
            raise InvalidMatrix("INVALID_CASE")
        serialized_name = json.dumps(entry["username"], ensure_ascii=True)
        allow = "true" if entry["allow"] else "false"
        lines.append(
            f"  - {{username: {serialized_name}, "
            f"document_id: {entry['document_id']}, allow: {allow}}}"
        )
    return "\n".join(lines) + "\n"


def write_private(path, contents):
    if not isinstance(path, Path) or path.name != ALLOWED_FILE:
        raise InvalidMatrix("UNEXPECTED_OUTPUT_FILENAME")
    if path.is_symlink() or path.exists():
        raise InvalidMatrix("TARGET_ALREADY_EXISTS")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise InvalidMatrix("OUTPUT_DIRECTORY_NOT_FOUND")
    if not isinstance(contents, str) or len(contents) > 16000:
        raise InvalidMatrix("INVALID_OUTPUT")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def ask_user(tag):
    value = getpass(f"Paperless-Benutzerkennung Konto {tag} (Eingabe verborgen): ").strip()
    if not USER_RE.fullmatch(value):
        raise InvalidMatrix("INVALID_IDENTITIES")
    return value


def ask_doc(name):
    value = getpass(f"Dokument-ID: {name} (Eingabe verborgen): ").strip()
    if not value.isdecimal() or len(value) > 12:
        raise InvalidMatrix("INVALID_DOCUMENT_IDS")
    return int(value)


def main():
    parser = argparse.ArgumentParser(description="Create a private reviewed Paperless ACL matrix")
    parser.add_argument("--base", required=True, help="Existing main working tree")
    parser.add_argument("--profile", choices=sorted(SCOPE_RULES), default="balanced",
                        help="Choose no-private-b when account B has no private document")
    args = parser.parse_args()
    basedir = Path(args.base).expanduser().resolve()
    if not (basedir / "ansible" / "vars").is_dir():
        raise InvalidMatrix("INVALID_BASE_DIRECTORY")
    out = basedir / "ansible" / "vars" / ALLOWED_FILE
    if out.exists() or out.is_symlink():
        raise InvalidMatrix("TARGET_ALREADY_EXISTS")
    # Intentionally do not inspect current Paperless permissions or user/group
    # lists: doing so would risk using the actual ACL as the policy expectation.
    print("Nur lokal, keine Paperless-Abfrage und kein produktiver Rechte-Write.")
    print("Zwei echte OIDC-verknuepfte, nichtprivilegierte Paperless-Konten.")
    print("Profil: " + args.profile)
    print("Erwartung: nur bestaetigte private und Gruppen-Dokumente.")
    if args.profile == "no-private-b":
        print("ACHTUNG: Fuer Konto A gibt es KEINEN Negativtest.")
        print("Die KI-Freigabe bleibt gesperrt, auch nach erfolgreichem Audit.")
    print("Keine Kindertrennung bewiesen. Keine aktuellen ACLs kopiert.")
    users = [ask_user("A"), ask_user("B")]
    ids = [ask_doc(name) for name, _ in SCOPE_RULES[args.profile]]
    cases = build_cases(users, ids, args.profile)
    allows = sum(x["allow"] for x in cases)
    denies = len(cases) - allows
    print("Erwartete Tests:", len(cases), "davon erlaubt:", allows, "verweigert:", denies)
    approved = input(
        "Sind Konten, Dokumentkategorien und Sollrechte unabhaengig geprueft? "
        "Tippe EXAKT 'FREIGABE': "
    ).strip()
    if approved != "FREIGABE":
        raise InvalidMatrix("REVIEW_NOT_APPROVED")
    write_private(out, render_matrix(cases, args.profile))
    # Do not disclose usernames, document IDs, or private matrix contents.
    print("PRIVATE_MATRIX_CREATED=YES")
    print("FILE_MODE=0600")
    print("PROFILE=" + args.profile)
    print("CASES=" + str(len(cases)))
    print("EXPECTED_ALLOWED=" + str(allows))
    print("EXPECTED_DENIED=" + str(denies))
    print("PER_ACTOR_DENY_COVERAGE=" +
          ("BOTH_ACTORS" if args.profile == "balanced" else "ONLY_ONE_ACTOR"))
    print("PAPERLESS_ACL_READ=NO")
    print("PRODUCTION_CHANGED=NO")


if __name__ == "__main__":
    try:
        main()
    except (InvalidMatrix, OSError, KeyboardInterrupt):
        print("PRIVATE_MATRIX_CREATED=NO")
        raise SystemExit(2)
