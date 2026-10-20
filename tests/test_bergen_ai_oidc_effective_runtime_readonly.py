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
        self.assertIn("os.environ", src)
        self.assertIn("ENABLE_OAUTH_PERSISTENT_CONFIG", src)
        self.assertIn("RUNNING_CONTAINER_ENV_V0_10_2", src)
        self.assertIn("IN_PROCESS_EFFECTIVE_CONFIG", src)
        self.assertNotIn("from open_webui", src)
        self.assertNotIn("import open_webui", src)
        self.assertIn("ENABLE_OAUTH_GROUP_MANAGEMENT", src)
        self.assertIn("OAUTH_GROUPS_CLAIM", src)
        self.assertIn("OAUTH_BLOCKED_GROUPS", src)
        self.assertIn("OIDC_CALLBACK_OBSERVED", src)
        self.assertIn("NOT_MEASURED", src)
        self.assertIn("OAUTH_PERSISTENCE_NOT_COVERED", src)
        self.assertIn("BLOCKED_GROUPS_FORMAT_UNREVIEWED", src)
        self.assertIn("UNEXPECTED_RUNTIME_FAILURE", src)
        self.assertIn('"AUDIT": "FAILED_CLOSED"', src)
        self.assertIn('raise SystemExit(2) from None', src)
        self.assertNotIn('asyncio.run', src)
        self.assertNotIn('GROUP_MANAGEMENT_EFFECTIVE', src)
        self.assertNotIn("str(exc)", src)
        self.assertNotIn("traceback.print_exc", src)
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
        self.assertIn("BERGEN_PYTHON_EXEC_V1:OK", source)
        self.assertIn("BERGEN_PYTHON_APP_V1:PRESENT", source)
        self.assertIn("CONTAINER_PYTHON_EXEC_OR_MODULE_UNAVAILABLE", source)
        self.assertIn("CONTAINER_PYTHON_EXEC", source)
        self.assertIn("OPEN_WEBUI_MODULE", source)
        self.assertNotIn("bp_oidc_python_exec.stderr", source)
        self.assertNotIn("bp_oidc_python_module.stderr", source)
        self.assertIn("DIAGNOSTIC=READ_ONLY_FAILURE", source)
        self.assertIn("STATUS_FRAME_COUNT", source)
        self.assertIn("BLOCKED_GROUPS_FORMAT_UNREVIEWED", source)
        self.assertIn("IN_PROCESS_EFFECTIVE_CONFIG=NOT_MEASURED", source)
        self.assertIn("MISSING_OR_MALFORMED_FRAME", source)
        self.assertIn("Reject missing frames", source)
        self.assertNotIn("bp_oidc_effective_raw.stderr", source)
        self.assertNotIn("stdout | debug", source)


if __name__ == "__main__":
    unittest.main()
