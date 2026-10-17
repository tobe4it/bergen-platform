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
import inspect
import socket
from importlib.metadata import PackageNotFoundError, version

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


def verify_smbprotocol_version():
    # The low-level SMB2 API was reviewed against 1.17.0. Refuse
    # unknown versions before requesting any private credentials.
    try:
        installed = version("smbprotocol")
    except PackageNotFoundError:
        raise RuntimeError("SMBPROTOCOL_LIBRARY_UNAVAILABLE") from None
    demand(installed == "1.17.0")
    return installed


# Fixed phase labels only. Never report raw exceptions: SMB exceptions can
# include names, paths, usernames, server details and authentication state.
SAFE_PHASES = frozenset((
    "PRECHECK", "IMPORTS", "PASSWORD_INPUT", "CONNECT_OBJECT",
    "SMB_NEGOTIATE", "SESSION_SETUP", "TREE_CONNECT", "SHARE_ROOT_OPEN",
    "SHARE_ROOT_CLOSE", "NEGATIVE_VERDICT", "TEARDOWN",
    "PROTECTED_ENTRY_DELETE_OPEN", "PROTECTED_ENTRY_DELETE_CLOSE",
    "SITE_ROOT_DELETE_CHILD_OPEN", "SITE_ROOT_DELETE_CHILD_CLOSE",
    "PROTECTED_ROOT_ENUMERATION_OPEN", "PROTECTED_ROOT_ENUMERATION_CLOSE",
))


def safe_error_label(error):
    """Return only an allowlisted exception class and numeric NTSTATUS."""
    if type(error).__name__ == "SMBResponseException":
        category = "SMB_STATUS"
    elif isinstance(error, (OSError, ConnectionError, TimeoutError)):
        category = "TRANSPORT"
    elif isinstance(error, (AttributeError, ImportError, TypeError)):
        category = "LIBRARY_API"
    elif isinstance(error, (RuntimeError, ValueError)):
        category = "VALIDATION"
    else:
        category = "OTHER"
    try:
        status = getattr(error, "status", None)
    except Exception:
        status = None
    code = (f"0x{status:08X}" if type(status) is int and
            0 <= status <= 0xFFFFFFFF else "NO_STATUS")
    return category, code


def safe_exception_type(error):
    """Whitelist exact standard/library exception classes, never raw content."""
    possible = (
        "ValueError", "RuntimeError", "TypeError", "AttributeError",
        "OSError", "ConnectionError", "ConnectionRefusedError",
        "ConnectionResetError", "ConnectionAbortedError",
        "TimeoutError", "socket.timeout", "gaierror",
        "SMBException", "SMBResponseException", "SMBConnectionClosed",
        "SMBConnectionTimeout", "SMBAuthenticationError",
    )
    name = type(error).__name__
    return name if name in possible else "OTHER_EXCEPTION"


def safe_diagnostic(phase, error):
    label, status = safe_error_label(error)
    return ("SMB_PROBE_DIAGNOSTIC",
            phase if phase in SAFE_PHASES else "PRECHECK",
            label, status, safe_exception_type(error))


def tcp_preflight(server):
    """Check TCP/445 without SMB messages, credentials or filesystem writes.

    Success means TCP connectivity only, NEVER authentication or permission.
    Socket errors are safely categorized without exposing local addresses.
    """
    demand(isinstance(server, str) and SERVER.fullmatch(server))
    try:
        with socket.create_connection((server, 445), timeout=5):
            pass
    except Exception as error:
        print(*safe_diagnostic("CONNECT_OBJECT", error),
              file=sys.stderr, flush=True)
        raise RuntimeError("SMB_TCP_445_NOT_REACHABLE") from None
    print("SMB_TCP_445_REACHABLE")
    print("NO_SMB_AUTHENTICATION_ATTEMPTED")
    print("NO_SMB_MUTATING_REQUESTS_SENT")


def local_api_preflight():
    """Only inspect the installed library; no network or credentials."""
    verify_smbprotocol_version()
    from smbprotocol.connection import Connection
    from smbprotocol.exceptions import SMBResponseException
    from smbprotocol.header import NtStatus
    from smbprotocol.open import (
        CreateDisposition, CreateOptions, FileAttributes,
        ImpersonationLevel, Open, ShareAccess,
    )
    from smbprotocol.session import Session
    from smbprotocol.tree import TreeConnect

    for owner, name in (
        (Connection, "connect"), (Connection, "disconnect"),
        (Session, "connect"), (TreeConnect, "connect"),
        (Open, "create"), (Open, "close"),
    ):
        method = getattr(owner, name, None)
        demand(callable(method))
        inspect.signature(method)
    for owner, name in (
        (NtStatus, "STATUS_ACCESS_DENIED"),
        (CreateDisposition, "FILE_OPEN"),
        (CreateOptions, "FILE_DIRECTORY_FILE"),
        (FileAttributes, "FILE_ATTRIBUTE_DIRECTORY"),
        (ImpersonationLevel, "Impersonation"),
        (ShareAccess, "FILE_SHARE_READ"),
        (ShareAccess, "FILE_SHARE_WRITE"),
        (ShareAccess, "FILE_SHARE_DELETE"),
    ):
        demand(getattr(owner, name, None) is not None)
    demand(issubclass(SMBResponseException, Exception))
    return True


def execute(server, site, username):
    phase = "PRECHECK"
    connection = None
    password = None
    try:
        plan = validate_site(server, site, username)
        phase = "IMPORTS"
        local_api_preflight()
        from smbprotocol.connection import Connection
        from smbprotocol.exceptions import SMBResponseException
        from smbprotocol.header import NtStatus
        from smbprotocol.open import (
            CreateDisposition, CreateOptions, FileAttributes,
            ImpersonationLevel, Open, ShareAccess,
        )
        from smbprotocol.session import Session
        from smbprotocol.tree import TreeConnect

        phase = "PASSWORD_INPUT"
        password = getpass.getpass("SMB password (not logged): ")
        demand(bool(password))
        phase = "CONNECT_OBJECT"
        connection = Connection(uuid.uuid4(), server, 445)
        phase = "SMB_NEGOTIATE"
        connection.connect(timeout=15)
        phase = "SESSION_SETUP"
        session = Session(connection, username, password,
                          require_encryption=True)
        session.connect()
        phase = "TREE_CONNECT"
        tree = TreeConnect(session, "\\\\" + server + "\\" + site)
        tree.connect()
        # Verify this SMB identity can open the share root before
        # treating denied accesses under it as a security control.
        phase = "SHARE_ROOT_OPEN"
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
                phase = "SHARE_ROOT_CLOSE"
                root.close()

        outcomes = []
        for path, access, label in plan:
            phase = label + "_OPEN"
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
                    phase = label + "_CLOSE"
                    handle.close()
            verdict = classify_smb_result(error, NtStatus.STATUS_ACCESS_DENIED)
            outcomes.append((label, verdict))
            print("SMB2_ACCESS_INTENT", site, label, verdict, flush=True)
        phase = "NEGATIVE_VERDICT"
        demand(all(outcome == "DENIED" for _, outcome in outcomes))
    except Exception as exc:
        print(*safe_diagnostic(phase, exc), file=sys.stderr, flush=True)
        raise RuntimeError("SMB_NEGATIVE_ACCESS_PROBE_BLOCKED") from None
    finally:
        password = None
        if connection is not None:
            try:
                connection.disconnect(True)
            except Exception as exc:
                print(*safe_diagnostic("TEARDOWN", exc),
                      file=sys.stderr, flush=True)
                raise RuntimeError("SMB_NEGATIVE_ACCESS_PROBE_BLOCKED") from None
    print("ONE_AUTHENTICATED_SMB_IDENTITY_DENIED_ALL_CHECKED_INTENTS")
    print("NO_SMB_MUTATING_REQUESTS_SENT")
    print("NO_NAS_FILES_CHANGED")
    print("INDEPENDENT_BACKUP_RESTORE_NOT_TESTED")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-api-check", action="store_true")
    parser.add_argument("--tcp-preflight", action="store_true")
    parser.add_argument("--server")
    parser.add_argument("--site-share", choices=sorted(SITE_SHARES))
    parser.add_argument("--username")
    opts = parser.parse_args(argv)
    if opts.local_api_check:
        demand(not opts.tcp_preflight and
               not any((opts.server, opts.site_share, opts.username)))
        local_api_preflight()
        print("SMBPROTOCOL_LOCAL_API_CHECK_OK")
        print("NO_SMB_CONNECTION_ATTEMPTED")
        return
    if opts.tcp_preflight:
        demand(not opts.local_api_check and
               opts.server and not opts.site_share and not opts.username)
        tcp_preflight(opts.server)
        return
    demand(all((opts.server, opts.site_share, opts.username)))
    execute(opts.server, opts.site_share, opts.username)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("SMB_NEGATIVE_ACCESS_PROBE_BLOCKED", file=sys.stderr)
        raise SystemExit(2)
