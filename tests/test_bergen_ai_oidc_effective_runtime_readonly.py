"""Offline fail-closed checks of tokenless effective OIDC runtime inventory."""
import ast
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_oidc_effective_runtime_v0102.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-oidc-effective-runtime-readonly.yml"


class EffectiveOidcRuntimeAudit(unittest.TestCase):
    def test_helper_is_read_only_and_returns_no_sensitive_claims(self):
        src = SCRIPT.read_text()
        ast.parse(src)
        self.assertIn("get_oauth_runtime_config", src)
        self.assertIn("Config.OAUTH_PERSISTENT_ENABLED", src)
        self.assertIn("ENABLE_OAUTH_GROUP_MANAGEMENT", src)
        self.assertIn("OAUTH_GROUPS_CLAIM", src)
        self.assertIn("OAUTH_BLOCKED_GROUPS", src)
        self.assertIn("OIDC_CALLBACK_OBSERVED", src)
        self.assertIn("NOT_MEASURED", src)
        self.assertNotIn("access_token", src)
        self.assertNotIn("client_secret", src)
        self.assertNotIn("userinfo", src)
        self.assertNotIn(".upsert(", src)
        self.assertNotIn(".save(", src)
        self.assertNotIn(".commit(", src)

    def test_ansible_version_pinned_and_readonly_without_api_bearer(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "bergen-ai")
        tasks = play["tasks"]
        assert_version = next(t for t in tasks
                              if t["name"].startswith("Require version matching"))
        self.assertIn("['0.10.2', 'v0.10.2']",
                      str(assert_version["ansible.builtin.assert"]))
        cmd = next(t for t in tasks if "ansible.builtin.command" in t)
        self.assertTrue(cmd["no_log"])
        self.assertEqual(cmd["changed_when"], False)
        self.assertEqual(cmd["ansible.builtin.command"]["argv"][:4],
                         ["podman", "exec", "open-webui", "python3"])
        source = PLAY.read_text()
        self.assertNotIn("vault_open_webui_admin_token", source)
        for forbidden in ("ansible.builtin.copy:", "ansible.builtin.replace:",
                          "ansible.builtin.lineinfile:", "ansible.builtin.shell:",
                          "ansible.builtin.systemd:"):
            self.assertNotIn(forbidden, source)
        self.assertIn("MEMBERSHIP_WRITE_OBSERVED=NOT_MEASURED", source)


if __name__ == "__main__":
    unittest.main()
