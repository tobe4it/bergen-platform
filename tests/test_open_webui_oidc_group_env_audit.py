"""Static no-write contracts for the OIDC group environment audit."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "ansible/playbooks/audit-open-webui-oidc-group-env-readonly.yml"


class OidcGroupEnvAuditTests(unittest.TestCase):
    def setUp(self):
        self.source = AUDIT.read_text()
        play = yaml.safe_load(self.source)
        self.assertEqual(len(play), 1)
        self.play = play[0]

    def test_target_requires_local_proxmox_identity(self):
        self.assertIn("__no_approved_pve_host__", self.play["hosts"])
        self.assertTrue(self.play["become"])
        self.assertFalse(self.play["gather_facts"])
        assertions = self.play["tasks"][0]["ansible.builtin.assert"]["that"]
        for clause in ("inventory_hostname == open_webui_oidc_audit_pve_host",
                       "open_webui_oidc_audit_vmid | int >= 100",
                       "open_webui_oidc_audit_guest is defined"):
            self.assertIn(clause, assertions)

    def test_no_mutations_and_redacted_command(self):
        permitted = {"ansible.builtin.assert", "ansible.builtin.command", "ansible.builtin.debug"}
        for task in self.play["tasks"]:
            actions = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(actions), 1, task["name"])
            self.assertIn(actions[0], permitted)
            if actions[0] == "ansible.builtin.command":
                self.assertFalse(task["changed_when"], task["name"])
                self.assertFalse(task["check_mode"], task["name"])
        cmd = next(t for t in self.play["tasks"] if t["name"].startswith("Read only"))
        self.assertTrue(cmd["no_log"])
        argv = cmd["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[0], "pct")
        self.assertIn("podman", argv)
        self.assertIn("exec", argv)
        self.assertNotIn("restart", self.source.lower().split("register: oidc_audit_flags", 1)[0])
        self.assertNotIn("ansible.builtin.copy", self.source)
        self.assertNotIn("ansible.builtin.template", self.source)
        self.assertNotIn("ansible.builtin.uri", self.source)

    def test_audit_explicitly_excludes_effective_persisted_permissions(self):
        for marker in ("EFFECTIVE_PERSISTED_CONFIG_NOT_VERIFIED=true",
                       "GROUP_REVOCATION_NOT_VERIFIED=true",
                       "NO_SERVICE_RESTART_OR_SETTINGS_CHANGE=true"):
            self.assertIn(marker, self.source)
        self.assertNotIn("vault_open_webui_admin_token", self.source)
        self.assertNotIn("vault_open_webui_oidc_client_secret", self.source)
        self.assertNotIn("192.168.", self.source)
        self.assertNotIn("thebergens.net", self.source)


if __name__ == "__main__":
    unittest.main()
