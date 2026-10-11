"""Read-only certificate source and proxy target audit contracts."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/preflight-proxy-certbot-tls.yml"
S = PLAY.read_text()


class ProxyCertbotAudit(unittest.TestCase):
    def setUp(self):
        self.plays = yaml.safe_load(S)

    def test_uses_existing_certbot_source_not_new_issuance(self):
        self.assertEqual(len(self.plays), 4)
        first = self.plays[0]
        joined = str(first)
        for name in ("mail_tls_source_address", "mail_tls_source_ssh_user",
                     "mail_tls_source_cert_file", "mail_tls_source_key_file",
                     "mail_tls_required_san"):
            self.assertIn(name, joined)
        self.assertNotIn("certbot certonly", S)
        self.assertNotIn("certbot renew", S)

    def test_no_writes_or_private_key_fetch(self):
        permitted = {
            "ansible.builtin.assert", "ansible.builtin.add_host",
            "ansible.builtin.stat", "ansible.builtin.command",
            "ansible.builtin.shell", "ansible.builtin.set_fact",
            "ansible.builtin.debug",
        }
        for play in self.plays:
            self.assertFalse(play["gather_facts"])
            for task in play["tasks"]:
                modules = [k for k in task if k.startswith("ansible.builtin.")]
                self.assertEqual(len(modules), 1, task["name"])
                self.assertIn(modules[0], permitted, task["name"])
                if modules[0] in ("ansible.builtin.command", "ansible.builtin.shell"):
                    self.assertIs(task.get("changed_when"), False)
                    self.assertIs(task.get("check_mode"), False)
        for forbidden in ("ansible.builtin.fetch", "ansible.builtin.slurp",
                          "ansible.builtin.copy", "ansible.builtin.file",
                          "ansible.builtin.apt", "ansible.builtin.service"):
            self.assertNotIn(forbidden, S)

    def test_all_ssh_and_key_invariants_explicit(self):
        self.assertIn("StrictHostKeyChecking=yes", S)
        self.assertIn("pct_ssh_proxy.py", S)
        self.assertIn("unprotected", S)
        self.assertIn("checkend", S)
        self.assertIn("checkhost", S)
        self.assertIn("openssl pkey", S)
        self.assertIn("proxy_tls_source_key_digest.stdout", S)
        self.assertIn("private_key_transferred: false", S)

    def test_public_generic_no_real_site_data(self):
        for value in ("192.168.", "thebergens.net", "BEGIN PRIVATE KEY", "BC:24:"):
            self.assertNotIn(value, S)


if __name__ == "__main__":
    unittest.main()
