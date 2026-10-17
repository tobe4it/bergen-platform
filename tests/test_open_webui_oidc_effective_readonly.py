"""Offline no-write contracts for the effective OAuth group security audit."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ansible/playbooks/audit-open-webui-oidc-effective-readonly.yml"


class EffectiveOIDCAuditContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text(encoding="utf-8")
        cls.plays = yaml.safe_load(cls.source)
        cls.tasks = cls.plays[0]["tasks"]

    def test_fail_closed_exactly_one_explicit_target(self):
        self.assertEqual(len(self.plays), 1)
        p = self.plays[0]
        self.assertFalse(p["gather_facts"])
        self.assertEqual(p["serial"], 1)
        self.assertIn("__no_selected_host__", p["hosts"])
        a = self.tasks[0]["ansible.builtin.assert"]["that"]
        self.assertIn("ansible_play_hosts_all | length == 1", a)
        self.assertIn("open_webui_oidc_effective_audit_approved | default(false) | bool", a)
        self.assertIn("vault_open_webui_admin_token is defined", a)
        self.assertTrue(self.tasks[0]["no_log"])

    def test_only_four_approved_http_gets_and_localhost(self):
        reqs = [t for t in self.tasks if "ansible.builtin.uri" in t]
        self.assertEqual(len(reqs), 4)
        expected = {
            "/api/version", "/api/v1/auths/admin/config/oauth",
            "/api/v1/auths/admin/config", "/api/v1/auths/admin/config/ldap"
        }
        got = set()
        for task in reqs:
            opts = task["ansible.builtin.uri"]
            self.assertEqual(opts["method"], "GET")
            self.assertEqual(opts["status_code"], 200)
            self.assertEqual(opts["follow_redirects"], "none")
            self.assertFalse(opts["use_proxy"])
            self.assertTrue(opts["url"].startswith("http://127.0.0.1:3000/"))
            self.assertTrue(task["no_log"])
            self.assertFalse(task["changed_when"])
            self.assertFalse(task["check_mode"])
            got.add(opts["url"].removeprefix("http://127.0.0.1:3000"))
            if opts["url"] != "http://127.0.0.1:3000/api/version":
                self.assertIn("vault_open_webui_admin_token", opts["headers"]["Authorization"])
        self.assertEqual(got, expected)

    def test_effective_config_is_redacted_and_strictly_classified(self):
        permitted = {
            "ansible.builtin.assert", "ansible.builtin.uri",
            "ansible.builtin.set_fact", "ansible.builtin.debug"
        }
        for task in self.tasks:
            actions = {k for k in task if k.startswith("ansible.builtin.")}
            self.assertEqual(len(actions), 1)
            self.assertTrue(actions <= permitted)
        validation = next(t for t in self.tasks if t["name"].startswith("Reject unknown"))
        self.assertTrue(validation["no_log"])
        for variable in (
            "ENABLE_OAUTH_GROUP_MANAGEMENT", "ENABLE_OAUTH_GROUP_CREATION",
            "ENABLE_OAUTH_ROLE_MANAGEMENT", "OAUTH_GROUP_CLAIM",
            "OAUTH_BLOCKED_GROUPS", "DEFAULT_USER_ROLE", "ENABLE_LDAP",
        ):
            self.assertIn(variable, str(validation["ansible.builtin.assert"]["that"]))
        fact = next(t for t in self.tasks if "ansible.builtin.set_fact" in t)
        self.assertTrue(fact["no_log"])
        dbg = next(t for t in self.tasks if "ansible.builtin.debug" in t)
        text = "\n".join(dbg["ansible.builtin.debug"]["msg"])
        self.assertNotIn("oidc_effective_oauth.json", text)
        self.assertNotIn("vault_open_webui_admin_token", text)
        self.assertIn("NO_SETTINGS_USERS_GROUPS_OR_SERVICES_CHANGED=true", text)
        self.assertIn("OIDC_ABSENT_CLAIM_REVOCATION_NOT_VERIFIED=true", text)
        self.assertIn("OIDC_EXISTING_SESSIONS_NOT_REVOKED=true", text)

    def test_no_prod_writes_and_no_private_site_identifiers(self):
        self.assertNotIn("ansible.builtin.template", self.source)
        self.assertNotIn("ansible.builtin.copy", self.source)
        self.assertNotIn("ansible.builtin.systemd_service", self.source)
        self.assertNotIn("ansible.builtin.shell", self.source)
        self.assertNotIn("ansible.builtin.command", self.source)
        self.assertNotIn("192.168.", self.source)
        self.assertNotIn("thebergens.net", self.source)
        self.assertNotIn("ENABLE_OAUTH_GROUP_MANAGEMENT=true", self.source)


if __name__ == "__main__":
    unittest.main()
