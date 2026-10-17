#!/usr/bin/env python3
"""No-write SMB2 access-intent gate for active protected Paperless archive roots.

Uses smbprotocol with CREATE disposition FILE_OPEN only. No create-on-missing,
SET_INFO, WRITE, DELETE_ON_CLOSE, rename, mkdir, unlink, or mutation commands.
Asks whether one explicitly selected authenticated SMB identity can obtain
DELETE on the archive-root entry, FILE_DELETE_CHILD on the parent share root,
or FILE_LIST_DIRECTORY on the archive root. A successful dangerous open
blocks. Only STATUS_ACCESS_DENIED is a proven denial. Any other error is
INCONCLUSIVE. Does not replace a controlled disposable SMB rename test.

The operator supplies a nonadministrative SMB account explicitly; its secret
is read using getpass and is never printed or stored. A share must map to
the EXACT Synology Btrfs site root, not an arbitrary nested share.
"""
import argparse
import getpass
import re
import sys
import uuid

SITE_SHARES = frozenset(("homes", "paperless-scan"))
ROOT = ".bergen-paperless-archive"
USERNAME = re.compile(r"[A-Za-z0-9_.@-]{1,128}\Z")
SERVER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}\Z")
DENIED_IDENTITIES = frozenset(("root", "supervisor", "admin",
                               "administrator", "paperless-sync"))
# All desired access bits are evaluated by the server on FILE_OPEN.
READ_ATTRIBUTES = 0x00000080
FILE_LIST_DIRECTORY = 0x00000001
DELETE = 0x00010000
FILE_DELETE_CHILD = 0x00000040


def demand(condition):
    if not condition:
        raise RuntimeError("SMB_NEGATIVE_ACCESS_GATE_BLOCKED")


def request_plan(site):
    """Pure, immutable plan to audit the protected root and its parent."""
    demand(site in SITE_SHARES)
    return (
        (ROOT, DELETE, "PROTECTED_ENTRY_DELETE"),
        ("", FILE_DELETE_CHILD, "SITE_ROOT_DELETE_CHILD"),
        (ROOT, FILE_LIST_DIRECTORY, "PROTECTED_ROOT_ENUMERATION"),
    )


def classify_smb_result(error, status_access_denied):
    """Exception status is an NTSTATUS value, never string-parsed."""
    if error is None:
        return "GRANTED"
    if getattr(error, "status", None) == status_access_denied:
        return "DENIED"
    return "INCONCLUSIVE"


def validate_site(server, site, username):
    demand(isinstance(server, str) and SERVER.fullmatch(server)
           and isinstance(site, str) and site in SITE_SHARES
           and isinstance(username, str) and USERNAME.fullmatch(username)
           and username.casefold() not in DENIED_IDENTITIES
           and "/" not in username and "\\" not in username)
    return request_plan(site)


def execute(server, site, username):
    plan = validate_site(server, site, username)
    password = getpass.getpass("SMB password (not logged): ")
    demand(bool(password))
    try:
        from smbprotocol.connection import Connection
        from smbprotocol.exceptions import SMBResponseException
        from smbprotocol.header import NtStatus
        from smbprotocol.open import (
            CreateDisposition, CreateOptions, FileAttributes,
            ImpersonationLevel, Open, ShareAccess,
        )
        from smbprotocol.session import Session
        from smbprotocol.tree import TreeConnect
    except ImportError:
        raise RuntimeError("SMBPROTOCOL_LIBRARY_UNAVAILABLE") from None

    connection = Connection(uuid.uuid4(), server, 445)
    try:
        connection.connect(timeout=15)
        session = Session(connection, username, password,
                          require_encryption=True)
        session.connect()
        tree = TreeConnect(session, "\\\\" + server + "\\" + site)
        tree.connect()
        # Verify the requested SMB share is actually accessible before
        # interpreting denied protected child opens as authorization proof.
        # READ_ATTRIBUTES request is a no-write FILE_OPEN on the share root.
        root = Open(tree, "")
        root_opened = False
        try:
            root.create(
                ImpersonationLevel.Impersonation,
                READ_ATTRIBUTES,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE
                | ShareAccess.FILE_SHARE_DELETE,
                CreateDisposition.FILE_OPEN, CreateOptions.FILE_DIRECTORY_FILE)
            root_opened = True
        finally:
            if root_opened:
                root.close(False)
        outcomes = []
        for path, access, label in plan:
            handle = Open(tree, path)
            error = None
            handle_opened = False
            try:
                handle.create(
                    ImpersonationLevel.Impersonation,
                    access,
                    FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                    ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE
                    | ShareAccess.FILE_SHARE_DELETE,
                    CreateDisposition.FILE_OPEN,
                    CreateOptions.FILE_DIRECTORY_FILE)
                handle_opened = True
            except SMBResponseException as exc:
                error = exc
            finally:
                if handle_opened:
                    handle.close(False)
            verdict = classify_smb_result(error, NtStatus.STATUS_ACCESS_DENIED)
            outcomes.append((label, verdict))
            print("SMB2_ACCESS_INTENT", site, label, verdict, flush=True)
        demand(all(outcome == "DENIED" for _, outcome in outcomes))
    finally:
        password = None
        connection.disconnect(True)
    print("ONE_AUTHENTICATED_SMB_IDENTITY_DENIED_ALL_CHECKED_INTENTS")
    print("NO_SMB_MUTATING_REQUESTS_SENT")
    print("NO_NAS_FILES_CHANGED")
    print("INDEPENDENT_BACKUP_RESTORE_NOT_TESTED")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--site-share", required=True,
                        choices=sorted(SITE_SHARES))
    parser.add_argument("--username", required=True)
    opts = parser.parse_args(argv)
    execute(opts.server, opts.site_share, opts.username)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("SMB_NEGATIVE_ACCESS_PROBE_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
