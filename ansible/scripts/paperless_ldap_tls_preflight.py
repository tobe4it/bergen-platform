#!/usr/bin/env python3
"""Verify the reviewed LDAP endpoint using Python's CA and hostname checks.

Read-only TLS handshake: no LDAP bind, credentials, or directory queries.
Fail closed on invalid trust, hostname, timeout, or TLS negotiation.
"""
from __future__ import annotations

import argparse
import socket
import ssl
import sys

HOST = "ldap.thebergens.net"
PORT = 636


def verify_ldaps(*, cafile: str | None = None) -> str:
    context = ssl.create_default_context(cafile=cafile)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((HOST, PORT), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=HOST) as secured:
            if not secured.getpeercert():
                raise ssl.SSLError("LDAP endpoint supplied no verifiable certificate")
            return secured.version() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cafile",
        help="Optional reviewed CA PEM (read-only). No insecure skip-verify mode.",
    )
    args = parser.parse_args()

    try:
        version = verify_ldaps(cafile=args.cafile)
    except (OSError, ssl.SSLError) as exc:
        print(
            f"LDAPS_TLS_FAIL host={HOST} port={PORT} reason={type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    print(
        f"LDAPS_TLS_PASS host={HOST} port={PORT} "
        f"ca_and_hostname_verified=true tls={version}"
    )
    print("LDAP_BIND=NOT_PERFORMED CONFIG_CHANGES=NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
