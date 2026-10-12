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

    def test_role_task_list_is_unique_and_postgres_validation_complete(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        names = [task["name"] for task in tasks]
        self.assertEqual(len(names), 14)
        self.assertEqual(len(names), len(set(names)))
        assertions = tasks[0]["ansible.builtin.assert"]["that"]
        self.assertTrue(any("paperless_postgres_image.split" in x
                            and "match(" in x and "$" in x for x in assertions))
        self.assertEqual(tasks[-1]["ansible.builtin.debug"]["msg"]["backup_required"], True)

    def test_secret_names_are_vault_prefixed_and_documented(self):
        example = yaml.safe_load((
            ROOT / "docs/examples/paperless.vault.example.yml").read_text())
        self.assertEqual(set(example), {
            "vault_paperless_secret_key",
            "vault_paperless_db_password",
            "vault_paperless_admin_password",
        })
        documentation = (ROOT / "docs/PAPERLESS-BACKEND.md").read_text()
        self.assertIn("ansible-vault create", documentation)
        self.assertIn("--ask-vault-pass", documentation)

    def test_separate_runtime_gate_only_installs_podman(self):
        path = ROOT / "ansible/playbooks/prepare-paperless-runtime.yml"
        data = yaml.safe_load(path.read_text())
        self.assertEqual(len(data), 1)
        stage = data[0]
        self.assertEqual(stage["hosts"], "paperless_nodes")
        checks = stage["pre_tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertTrue(any("paperless_runtime_approved" in x for x in checks))
        self.assertTrue(any("pct_ssh_proxy.py" in x for x in checks))
        self.assertTrue(any("StrictHostKeyChecking=yes" in x for x in checks))
        apt_tasks = [task for task in stage["tasks"] if
                     "ansible.builtin.apt" in task]
        self.assertEqual(len(apt_tasks), 1)
        self.assertEqual(set(apt_tasks[0]["ansible.builtin.apt"]["name"]),
                         {"podman", "uidmap", "fuse-overlayfs", "slirp4netns"})
        for task in stage["tasks"]:
            self.assertNotIn("ansible.builtin.systemd", task)
            self.assertNotIn("ansible.builtin.template", task)
        self.assertIn("podman, info, --format, json", path.read_text())

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

    def test_mount_gate_precedes_filesystem_writes(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        names = [task["name"] for task in tasks]
        require = names.index(
            "Require active dedicated ZFS volume before writing application data")
        mkdir = names.index(
            "Create protected service and persistent application directories")
        self.assertLess(require, mkdir)
        assert_lines = tasks[require]["ansible.builtin.assert"]["that"]
        self.assertTrue(any("paperless_document_mount.stdout" in line
                            for line in assert_lines))
        self.assertTrue(any("'zfs'" in line for line in assert_lines))

    def test_quadlets_boot_disabled_until_explicit_start_approval(self):
        for path in (ROLE / "templates").glob("*.container.j2"):
            tpl = path.read_text()
            self.assertIn("{% if paperless_start_approved | bool %}", tpl)
            self.assertIn("WantedBy=multi-user.target", tpl)
        tasks = (ROLE / "tasks/main.yml").read_text()
        self.assertIn("Refuse unintended Paperless service activation", tasks)
        self.assertNotIn("enabled: true", tasks)

    def test_paperless_explicitly_selects_postgresql(self):
        env = (ROLE / "templates/paperless.env.j2").read_text()
        self.assertIn("PAPERLESS_DBENGINE=postgresql", env)
        self.assertIn("PAPERLESS_DBHOST=bergen-paperless-db", env)
        self.assertIn("PAPERLESS_DBNAME=paperless", env)
        self.assertIn("PAPERLESS_REDIS=redis://bergen-paperless-redis:6379", env)

    def test_secrets_only_in_protected_templates(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        for path in ("paperless.env", "postgres.env"):
            self.assertIn(path, tasks)
        self.assertIn("mode: '0600'", tasks)
        self.assertIn("no_log: true", tasks)
        defaults = (ROLE / "defaults/main.yml").read_text()
        tasks = (ROLE / "tasks/main.yml").read_text()
        for name in ("vault_paperless_secret_key", "vault_paperless_db_password",
                     "vault_paperless_admin_password"):
            self.assertNotIn(name + ":", defaults)
            self.assertIn(name + " is defined", tasks)
        app_env = (ROLE / "templates/paperless.env.j2").read_text()
        pg_env = (ROLE / "templates/postgres.env.j2").read_text()
        for name in ("vault_paperless_secret_key", "vault_paperless_db_password",
                     "vault_paperless_admin_password"):
            self.assertTrue(name in app_env or name in pg_env)
        for name in ("PAPERLESS_SECRET_KEY", "PAPERLESS_DBPASS",
                     "PAPERLESS_ADMIN_PASSWORD"):
            self.assertIn(name, app_env)

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
        self.assertIn("ansible/vars/paperless.local.yml", ignore)
        self.assertIn("ansible/vars/paperless.vault.yml", ignore)
        self.assertNotIn("paperless_secret_key:", (
            ROOT / "docs/examples/paperless.local.example.yml").read_text())
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
