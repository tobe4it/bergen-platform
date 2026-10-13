"""Offline contract tests for non-enrolling, opt-in Synology Paperless OIDC."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "ansible/roles/paperless/defaults/main.yml"
TEMPLATE = ROOT / "ansible/roles/paperless/templates/paperless.env.j2"
TASKS = ROOT / "ansible/roles/paperless/tasks/main.yml"
DOC = ROOT / "docs/PAPERLESS-SYNOLOGY-OIDC.md"


class SynologyOIDCStagingTests(unittest.TestCase):
    def test_staged_disabled_by_default(self):
        defaults = DEFAULTS.read_text(encoding="utf-8")
        self.assertIn("paperless_synology_oidc_enabled: false", defaults)
        self.assertIn("paperless_synology_oidc_configuration_approved: false", defaults)
        self.assertIn("paperless_synology_oidc_discovery_url: ''", defaults)

    def test_template_disallows_unreviewed_accounts_and_groups(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{% if paperless_synology_oidc_enabled | bool %}", template)
        self.assertIn("provider_id': 'synology'", template)
        self.assertIn("vault_paperless_synology_oidc_client_id", template)
        self.assertIn("vault_paperless_synology_oidc_client_secret", template)
        self.assertIn("paperless_synology_oidc_discovery_url", template)
        self.assertIn("\'SCOPE\': [\'openid\', \'email\']", template)
        for line in (
            "PAPERLESS_SOCIAL_AUTO_SIGNUP=false",
            "PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS=false",
            "PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS=false",
            "PAPERLESS_DISABLE_REGULAR_LOGIN=false",
            "PAPERLESS_REDIRECT_LOGIN_TO_SSO=false",
            "PAPERLESS_CONSUMER_RECURSIVE=false",
        ):
            self.assertIn(line, template)
        self.assertNotIn("PAPERLESS_SOCIAL_ACCOUNT_SYNC_SUPERUSER_GROUP=", template)
        self.assertNotIn("PAPERLESS_SOCIAL_ACCOUNT_SYNC_STAFF_GROUP=", template)

    def test_role_uses_explicit_gate_and_secret_redaction(self):
        tasks = TASKS.read_text(encoding="utf-8")
        self.assertIn("paperless_synology_oidc_configuration_approved | bool", tasks)
        self.assertIn("when: paperless_synology_oidc_enabled | bool", tasks)
        self.assertIn("no_log: true", tasks)
        self.assertIn("paperless_synology_oidc_discovery_url", tasks)

    def test_documentation_retains_break_glass_account_and_protects_secret(self):
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("break-glass", doc)
        self.assertIn("Until proven", doc)
        self.assertIn("PREPARED, NOT DEPLOYED", doc)


if __name__ == "__main__":
    unittest.main()
