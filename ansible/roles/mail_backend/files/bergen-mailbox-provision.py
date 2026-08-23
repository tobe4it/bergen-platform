#!/usr/bin/env python3
"""Provision missing Dovecot Maildir INBOXes for LDAP Mailuser members.

The program is intentionally create-only. Removing an LDAP account or group
membership never deletes mail data.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from ldap3 import ALL, AUTO_BIND_NO_TLS, AUTO_BIND_TLS_BEFORE_BIND, Connection, Server, Tls


CONFIG_PATH = Path("/etc/bergen-platform/mailbox-provision.json")
SAFE_LOCAL_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def load_config() -> dict[str, object]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ldap_connection(config: dict[str, object]) -> Connection:
    parsed = urlparse(str(config["ldap_uri"]))
    if parsed.scheme not in {"ldap", "ldaps"} or not parsed.hostname:
        raise ValueError("ldap_uri must use ldap:// or ldaps://")

    validate = ssl.CERT_REQUIRED if config["validate_certificate"] else ssl.CERT_NONE
    tls = Tls(
        validate=validate,
        ca_certs_file=str(config["ca_file"]) or None,
    )
    server = Server(
        parsed.hostname,
        port=parsed.port or (636 if parsed.scheme == "ldaps" else 389),
        use_ssl=parsed.scheme == "ldaps",
        tls=tls,
        get_info=ALL,
    )

    auto_bind = (
        AUTO_BIND_TLS_BEFORE_BIND
        if config["start_tls"] and parsed.scheme == "ldap"
        else AUTO_BIND_NO_TLS
    )
    return Connection(
        server,
        user=str(config["bind_dn"]),
        password=str(config["bind_password"]),
        auto_bind=auto_bind,
        raise_exceptions=True,
    )


def mailbox_exists(address: str) -> bool:
    result = subprocess.run(
        ["doveadm", "mailbox", "status", "-u", address, "messages", "INBOX"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def create_mailbox(address: str) -> None:
    subprocess.run(
        ["doveadm", "mailbox", "create", "-u", address, "INBOX"],
        check=True,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    username_attribute = str(config["username_attribute"])
    domain = str(config["primary_domain"]).lower()

    created = 0
    skipped = 0
    invalid = 0

    with ldap_connection(config) as connection:
        connection.search(
            search_base=str(config["search_base"]),
            search_filter=str(config["search_filter"]),
            attributes=[username_attribute],
        )

        usernames = sorted(
            {
                str(entry[username_attribute].value).lower()
                for entry in connection.entries
                if username_attribute in entry
                and entry[username_attribute].value is not None
            }
        )

    for username in usernames:
        if not SAFE_LOCAL_PART.fullmatch(username):
            logging.error("Ignoring unsafe LDAP username %r", username)
            invalid += 1
            continue

        address = f"{username}@{domain}"
        if mailbox_exists(address):
            skipped += 1
            continue

        create_mailbox(address)
        logging.info("Created mailbox for %s", address)
        created += 1

    logging.info(
        "Provisioning complete: created=%d existing=%d invalid=%d",
        created,
        skipped,
        invalid,
    )
    return 1 if invalid else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.exception("Mailbox provisioning failed")
        sys.exit(1)
