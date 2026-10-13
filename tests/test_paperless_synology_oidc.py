"""Offline tests for the staged Synology SSO OpenID preflight."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "ansible/scripts/paperless_synology_oidc_preflight.py"
spec = importlib.util.spec_from_file_location("synology_oidc_preflight", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

URL = "https://sehnde.tbergen.de:5001/webman/sso/.well-known/openid-configuration"
META = {
    "issuer": "https://sehnde.tbergen.de:5001/webman/sso",
    "authorization_endpoint": "https://sehnde.tbergen.de:5001/webman/sso/SSOOauth.cgi",
    "token_endpoint": "https://sehnde.tbergen.de:5001/webman/sso/SSOAccessToken.cgi",
    "jwks_uri": "https://sehnde.tbergen.de:5001/webman/sso/openid-jwks.json",
    "id_token_signing_alg_values_supported": ["RS256"],
    "response_types_supported": ["code", "code id_token", "id_token", "id_token token"],
    "scopes_supported": ["email", "groups", "openid"],
}


class FakeResponse:
    status = 200

    def __init__(self, url: str, content: bytes):
        self.url = url
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return self.url

    def read(self, _maximum):
        return self.content


class SynologyOIDCPreflightTests(unittest.TestCase):
    def test_valid_metadata(self):
        mod.validate_metadata(URL, META)

    def test_rejects_wrong_origin_and_http(self):
        for url in (
            "http://ldap.thebergens.net:5001/webman/sso/.well-known/openid-configuration",
            "https://evil.example/webman/sso/.well-known/openid-configuration",
            "https://ldap.thebergens.net:8443/webman/sso/.well-known/openid-configuration",
            "https://ldap.thebergens.net:5001/webman/sso/.well-known/openid-configuration?x=1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mod.validate_metadata(url, META)

    def test_rejects_wrong_old_ldap_hostname(self):
        modified = dict(META, issuer="https://ldap.thebergens.net:5001/webman/sso")
        with self.assertRaises(ValueError):
            mod.validate_metadata(URL, modified)

    def test_rejects_unexpected_issuer(self):
        modified = dict(META, issuer="https://sehnde.tbergen.de:5001/other")
        with self.assertRaises(ValueError):
            mod.validate_metadata(URL, modified)

    def test_rejects_missing_rs256(self):
        modified = dict(META, id_token_signing_alg_values_supported=["none"])
        with self.assertRaises(ValueError):
            mod.validate_metadata(URL, modified)

    def test_rejects_foreign_token_endpoint(self):
        modified = dict(META, token_endpoint="https://evil.example/oauth/token")
        with self.assertRaises(ValueError):
            mod.validate_metadata(URL, modified)

    def test_rejects_redirect_before_accepting_metadata(self):
        import json

        response = FakeResponse(
            "https://sehnde.tbergen.de:5001/moved",
            json.dumps(META).encode(),
        )
        with patch.object(mod.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(ValueError):
                mod.probe(URL)


if __name__ == "__main__":
    unittest.main()
