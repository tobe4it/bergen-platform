"""Offline behavior and safety tests for mx1-only Nextcloud dependency inventory."""
import importlib.util
from pathlib import Path
from unittest import TestCase, mock
import unittest
import yaml

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / "ansible/files/mail/audit_mx1_nextcloud_dependencies_readonly.py"
PLAY = BASE / "ansible/playbooks/audit-mx1-nextcloud-dependencies-readonly.yml"
spec = importlib.util.spec_from_file_location("mx1_dep", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class MX1ReadOnlyDependencies(TestCase):
    def test_no_mutating_functions_or_approvals(self):
        code = SCRIPT.read_text()
        for bad in (
            "os.unlink(", "os.remove(", "os.rename(", "os.replace(",
            "os.mkdir(", "os.makedirs(", "os.chmod(", "os.chown(",
            "os.system(", "shell=True", "shutil.rmtree(", "open(path, 'w')",
            '"pct"', '"certbot"', '"rm"', '"truncate"', '"drop database"',
            '"mysqladmin"', '"nginx", "-s"', '"systemctl", "stop"'
        ):
            self.assertNotIn(bad, code)
        self.assertIn('"deletion_authorized": False', code)
        self.assertIn('"shared_certificate_deletion_authorized": False', code)
        self.assertIn('"database_drop_authorized": False', code)

    def test_mx1_identity_is_fail_closed(self):
        with mock.patch.object(m, "command", return_value=mock.Mock(stdout="mx.thebergens.net\n")), \
             mock.patch.object(m.os, "geteuid", return_value=0):
            with self.assertRaises(m.Blocked):
                m.run("mx1.thebergens.net")

    def test_effective_nginx_file_and_shared_literal_cert(self):
        nginx_dump = """
# configuration file /etc/nginx/nginx.conf:
events { }
# configuration file /etc/nginx/conf.d/cloud.tbergen.de.conf:
server {
 server_name cloud.tbergen.de;
 root /usr/share/nginx/de.tbergen.cloud/html;
 ssl_certificate /etc/letsencrypt/live/wildcard/fullchain.pem;
}
# configuration file /etc/nginx/conf.d/mail.conf:
server {
 server_name mail.tbergen.de;
 ssl_certificate /etc/letsencrypt/live/wildcard/fullchain.pem;
}
"""
        with mock.patch.object(m, "command",
                               return_value=mock.Mock(stdout=nginx_dump)):
            r = m.nginx_inventory()
        self.assertEqual(r["legacy_reference_allowlisted_files"],
                         ["/etc/nginx/conf.d/cloud.tbergen.de.conf"])
        self.assertEqual(r["cloud_server_name_declarations"], 1)
        self.assertTrue(r["literal_certificate_reuse_found"])
        self.assertFalse(r["certificate_consumers_fully_proven"])
        self.assertFalse(r["exclusive"])

    def test_unknown_nginx_include_fails_exclusivity(self):
        conf = """# configuration file /opt/unreviewed.conf:
server { server_name cloud.tbergen.de; }
"""
        with mock.patch.object(m, "command",
                               return_value=mock.Mock(stdout=conf)):
            r = m.nginx_inventory()
        self.assertEqual(r["legacy_reference_nonallowlisted_count"], 1)
        self.assertEqual(r["legacy_reference_allowlisted_files"], [])
        self.assertFalse(r["exclusive"])

    def test_inaccessible_db_not_treated_as_absent(self):
        with mock.patch.object(m, "command", return_value=None):
            self.assertEqual(m.database_scope()["legacy_nextcloud_schema"],
                             "UNKNOWN")

    def test_only_allowlisted_ansible_execution(self):
        yaml_source = PLAY.read_text()
        plays = yaml.safe_load(yaml_source)
        self.assertEqual(plays[0]["import_playbook"],
                         "audit-mx1-nextcloud-retirement-readonly.yml")
        self.assertEqual(plays[1]["hosts"], "selected_mx1_nextcloud_retirement")
        types = []
        for task in plays[1]["tasks"]:
            modules = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1)
            self.assertIn(modules[0], (
                "ansible.builtin.assert", "ansible.builtin.command",
                "ansible.builtin.debug"))
            types.append(modules[0])
            if modules[0] == "ansible.builtin.command":
                self.assertIs(task.get("no_log"), True)
                self.assertIs(task.get("changed_when"), False)
                self.assertIs(task.get("failed_when"), False)
                self.assertEqual(task[modules[0]]["argv"][:2],
                                 ["python3", "-c"])
        self.assertEqual(types.count("ansible.builtin.command"), 1)
        self.assertIn("deletion_authorized: false", yaml_source)
        self.assertIn("database_dropped: false", yaml_source)

if __name__ == "__main__":
    unittest.main()
