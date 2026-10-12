"""Offline security and syntax contracts for the proposed Paperless backend."""
from pathlib import Path
import unittest
import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/paperless"
PLAYBOOK = ROOT / "ansible/playbooks/deploy-paperless.yml"
PREFLIGHT = ROOT / "ansible/playbooks/preflight-paperless.yml"
IGNORE = ROOT / ".gitignore"


class PaperlessPrivateBackendTests(unittest.TestCase):
    def test_yaml_sources_parse_without_side_effects(self):
        for path in (PLAYBOOK, PREFLIGHT, ROLE / "defaults/main.yml",
                     ROLE / "tasks/main.yml",
                     ROOT / "docs/examples/paperless.local.example.yml"):
            self.assertTrue(yaml.safe_load(path.read_text()), str(path))

    def test_unapproved_by_default(self):
        data = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertIs(data["paperless_deployment_approved"], False)
        self.assertIs(data["paperless_start_approved"], False)
        self.assertEqual(data["paperless_listen_address"], "127.0.0.1")
        self.assertEqual(data["paperless_listen_port"], 8000)

    def test_localhost_only_web_port_and_private_services(self):
        app = (ROLE / "templates/bergen-paperless.container.j2").read_text()
        db = (ROLE / "templates/bergen-paperless-db.container.j2").read_text()
        broker = (ROLE / "templates/bergen-paperless-redis.container.j2").read_text()
        self.assertIn("PublishPort={{ paperless_listen_address }}:{{ paperless_listen_port }}:8000", app)
        self.assertNotIn("PublishPort=", db)
        self.assertNotIn("PublishPort=", broker)
        self.assertIn("Network=bergen-paperless.network", app)
        self.assertIn("Network=bergen-paperless.network", db)
        self.assertIn("Network=bergen-paperless.network", broker)
        self.assertIn("NoNewPrivileges=true", app)

    def test_secrets_only_in_protected_templates(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        for path in ("paperless.env", "postgres.env"):
            self.assertIn(path, tasks)
        self.assertIn("mode: '0600'", tasks)
        self.assertIn("no_log: true", tasks)
        self.assertNotIn("paperless_secret_key:", (ROLE / "defaults/main.yml").read_text())
        for name in ("PAPERLESS_SECRET_KEY", "PAPERLESS_DBPASS", "PAPERLESS_ADMIN_PASSWORD"):
            self.assertIn(name, (ROLE / "templates/paperless.env.j2").read_text())

    def test_separate_start_gate_and_target_pinning(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        play = PLAYBOOK.read_text()
        self.assertIn("paperless_start_approved | bool", tasks)
        self.assertIn("paperless_deployment_approved | bool", tasks)
        for expected in ("pct_ssh_proxy.py", "HostKeyAlias=lxc-",
                         "StrictHostKeyChecking=yes", "paperless_nodes",
                         "lxc_vmid", "ansible_facts['hostname']"):
            self.assertIn(expected, play)

    def test_no_credentials_or_site_topology_in_public_artifacts(self):
        paths = list((ROLE / "templates").glob("*")) + [
            ROLE / "tasks/main.yml", ROLE / "defaults/main.yml",
            PLAYBOOK, PREFLIGHT]
        for path in paths:
            contents = path.read_text()
            self.assertNotIn("thebergens.net", contents, str(path))
            self.assertNotIn("192.168.", contents, str(path))
            self.assertNotIn("BEGIN PRIVATE KEY", contents, str(path))
        ignore = IGNORE.read_text()
        self.assertIn("ansible/group_vars/all/paperless.local.yml", ignore)
        self.assertIn("ansible/group_vars/all/bergen-paperless.yml", ignore)

    def test_template_syntax_compiles(self):
        env = Environment()
        for path in (ROLE / "templates").glob("*.j2"):
            env.parse(path.read_text())

    def test_proxmox_preflight_has_no_write_modules(self):
        content = PREFLIGHT.read_text()
        for forbidden in ("pct create", "pct set", "ansible.builtin.apt:",
                          "ansible.builtin.file:", "ansible.builtin.copy:",
                          "ansible.builtin.template:", "ansible.builtin.systemd:",
                          "state: present", "state: started"):
            self.assertNotIn(forbidden, content)


if __name__ == "__main__":
    unittest.main()
