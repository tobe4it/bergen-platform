#!/usr/bin/env python3
"""Read-only, credential-free Synology SSO OpenID discovery probe.

Accept the exact OIDC Well-known URL copied from DSM SSO Server -> Dienst.
Never assumes a discovery path, disables TLS verification or sends tokens.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = "sehnde.tbergen.de"
DISCOVERY_URL = "https://sehnde.tbergen.de:5001/webman/sso/.well-known/openid-configuration"
ISSUER = "https://sehnde.tbergen.de:5001/webman/sso"
REQUIRED_KEYS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")


def require_https_endpoint(value: str, label: str, *, well_known: bool = False) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a URL string")
    uri = urllib.parse.urlsplit(value)
    try:
        port = uri.port
    except ValueError as exc:
        raise ValueError(f"{label}: invalid port") from exc
    if (
        uri.scheme != "https"
        or uri.hostname != HOST
        or port != 5001
        or uri.username is not None
        or uri.password is not None
        or uri.fragment
        or uri.query
    ):
        raise ValueError(f"{label}: unexpected scheme, host, port or URL parameters")
    if well_known and value != DISCOVERY_URL:
        raise ValueError("discovery URL does not match reviewed Synology OIDC endpoint")


def validate_metadata(url: str, data: object) -> None:
    require_https_endpoint(url, "discovery", well_known=True)
    if not isinstance(data, dict):
        raise ValueError("discovery response must be a JSON object")
    expected = {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/SSOOauth.cgi",
        "token_endpoint": ISSUER + "/SSOAccessToken.cgi",
        "jwks_uri": ISSUER + "/openid-jwks.json",
    }
    for key in REQUIRED_KEYS:
        if data.get(key) != expected[key]:
            raise ValueError(f"unexpected OIDC metadata: {key}")
        require_https_endpoint(data[key], key)
    if "RS256" not in data.get("id_token_signing_alg_values_supported", []):
        raise ValueError("OIDC metadata does not support RS256")
    if "code" not in data.get("response_types_supported", []):
        raise ValueError("OIDC metadata does not support authorization code")
    if "openid" not in data.get("scopes_supported", []):
        raise ValueError("OIDC metadata does not support openid scope")
    # A probe cannot prove that the issuer in future ID tokens will match.
    # That requires a separately reviewed end-to-end OIDC login test.


def probe(url: str) -> None:
    require_https_endpoint(url, "discovery", well_known=True)
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "bergen-platform-oidc-preflight/1"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
        if response.geturl() != url:
            raise ValueError("discovery URL redirected to an unexpected location")
        if response.status != 200:
            raise ValueError("unexpected HTTP response status")
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("discovery response exceeds 64 KiB")
    validate_metadata(url, json.loads(body))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("well_known_url", help="Exact Well-known URL displayed by Synology SSO Server")
    args = parser.parse_args()
    try:
        probe(args.well_known_url)
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, ssl.SSLError) as exc:
        print(f"SYNOLOGY_OIDC_DISCOVERY_FAIL reason={type(exc).__name__}", file=sys.stderr)
        return 1
    print("SYNOLOGY_OIDC_DISCOVERY_PASS metadata_and_tls_verified=true")
    print("TOKENS_TESTED=false PAPERLESS_CHANGED=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
