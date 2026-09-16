"""Offline lab provisioning contracts and actual generated-certificate tests."""
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/mq_lab"
IMAGE = "icr.io/ibm-messaging/mq:9.4.0.25-r3-amd64@sha256:56f294fb083d9030ba24e972f8c66d4888f76472d7eb8f6feae8d526eee39111"


def environment():
    env = Environment(undefined=StrictUndefined)
    env.filters["to_json"] = json.dumps
    env.filters["realpath"] = os.path.realpath
    return env


def render(template, **extra):
    context = dict(mq_lab_image=IMAGE, mq_lab_qmgr="BERGENLAB", inventory_hostname="bergen-mq-lab",
                   ansible_host="192.0.2.10", ansible_facts={},
                   mq_lab_controller_ca_path="/tmp/mq-evaluation-ca.crt")
    context.update(extra)
    return environment().from_string(template).render(context)


class LabContracts(unittest.TestCase):
    def test_admin_firewall_rules_are_https_only_and_preserve_controller(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(defaults["mq_lab_admin_cidrs"], [])
        tasks = yaml.safe_load((ROLE / "tasks/configure.yml").read_text())
        task = next(t for t in tasks if t["name"].startswith("Add browser admin HTTPS"))
        self.assertEqual(task["loop"], "{{ mq_lab_admin_cidrs }}")
        env = environment()
        env.filters["unique"] = lambda values: list(dict.fromkeys(values))
        controller = 'rule family="ipv4" source address="192.0.2.250/32" port port="9443" protocol="tcp" accept'
        result = env.compile_expression(task["ansible.builtin.set_fact"]["mq_lab_firewall_rules"][3:-3])(
            mq_lab_firewall_rules=[controller], item="192.168.2.0/23")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], controller)
        self.assertIn('source address="192.168.2.0/23"', result[1])
        self.assertIn('port port="9443"', result[1])
        self.assertNotIn("1414", result[1])

    def test_explicit_web_auth_does_not_enable_default_mq_objects(self):
        xml = render((ROLE / "templates/mqwebuser.xml.j2").read_text())
        root = ET.fromstring(xml)
        self.assertIn("basicAuthenticationMQ-1.0", [f.text for f in root.findall("featureManager/feature")])
        users = root.findall("basicRegistry/user")
        self.assertEqual([u.attrib["name"] for u in users], ["admin"])
        self.assertEqual(users[0].attrib["password"], "${env.MQ_ADMIN_PASSWORD_SECURE}")
        self.assertEqual(len(root.findall("enterpriseApplication/application-bnd/security-role[@name='MQWebAdmin']")), 2)
        quadlet = render((ROLE / "templates/bergen-mq-lab.container.j2").read_text())
        self.assertIn("Environment=MQ_DEV=false", quadlet)
        self.assertIn("/servers/mqweb/mqwebuser.xml:ro", quadlet)
        self.assertNotIn("MQ_ADMIN_PASSWORD=", quadlet)
        self.assertIn("mq_lab_web_config.changed", (ROLE / "tasks/service.yml").read_text())

    def test_all_basic_auth_readiness_requests_have_mq_csrf_header(self):
        tasks = yaml.safe_load((ROLE / "tasks/api.yml").read_text())
        requests = [t["ansible.builtin.uri"] for t in tasks if "ansible.builtin.uri" in t]
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertTrue(request["force_basic_auth"])
            self.assertIn("ibm-mq-rest-csrf-token", request["headers"])
            self.assertTrue(request["validate_certs"])
            self.assertFalse(request["use_proxy"])

    def test_ssh_preparation_runs_after_start_before_discovery(self):
        plays = yaml.safe_load((ROOT / "ansible/playbooks/deploy-mq-lab.yml").read_text())
        imports = [p["import_playbook"] for p in plays if "import_playbook" in p]
        self.assertLess(imports.index("restart-lxc.yml"), imports.index("prepare-mq-lxc-ssh.yml"))
        self.assertLess(imports.index("prepare-mq-lxc-ssh.yml"), imports.index("discover-lxc.yml"))

    def test_ssh_preparation_preserves_keys_and_checks_identity(self):
        path = ROOT / "ansible/playbooks/prepare-mq-lxc-ssh.yml"
        play = yaml.safe_load(path.read_text())[0]
        self.assertTrue(play["become"])
        tasks = play["tasks"]
        self.assertIn("ansible.builtin.assert", tasks[1])
        install = next(t for t in tasks if t["name"] == "Install OpenSSH server only when missing")
        self.assertEqual(install["when"], "mq_lab_sshd_package.rc == 1")
        text = path.read_text()
        for required in ["ssh-keygen, -A", "/usr/sbin/sshd, -t", "systemctl is-active --quiet sshd", "systemctl is-enabled --quiet sshd"]:
            self.assertIn(required, text)
        for forbidden in ["StrictHostKeyChecking=no", "PermitRootLogin", "PasswordAuthentication", "authorized_keys", "rm -", "unconfined=true"]:
            self.assertNotIn(forbidden, text)

    def test_all_new_yaml_parses(self):
        files = list(ROLE.rglob("*.yml")) + list((ROOT / "ansible/playbooks").glob("*mq*.yml"))
        for path in files:
            with self.subTest(path=path):
                self.assertIsInstance(yaml.safe_load(path.read_text()), (dict, list))

    def test_license_defaults_do_not_accept(self):
        for path in [ROLE / "defaults/main.yml", ROOT / "ansible/group_vars/all/bergen-mq-lab.yml.example"]:
            data = yaml.safe_load(path.read_text())
            self.assertFalse(data["mq_lab_confirm_test_only"])
            self.assertNotEqual(data["mq_lab_license_acceptance"], "accept")

    def test_template_is_pinned_and_confined(self):
        text = render((ROLE / "templates/bergen-mq-lab.container.j2").read_text())
        for required in ["Image=" + IMAGE, "Network=host", "DropCapability=all", "NoNewPrivileges=true",
                         "Secret=mqAdminPassword", "Secret=mqAppPassword", "ShmSize=512m",
                         "LogDriver=journald", "Pull=never", "WantedBy=multi-user.target",
                         "CONTAINERS_STORAGE_CONF=/etc/bergen-mq-lab/storage.conf"]:
            self.assertIn(required, text)
        for forbidden in ["latest", "Privileged=", "unconfined", "MQ_ADMIN_PASSWORD=", "MQ_APP_PASSWORD=", "SecurityLabelDisable=true"]:
            self.assertNotIn(forbidden, text)

    def test_selinux_volume_labels_only_when_active(self):
        template = (ROLE / "templates/bergen-mq-lab.container.j2").read_text()
        plain = render(template)
        labelled = render(template, ansible_facts=dict(selinux=dict(status="enabled")))
        self.assertIn("/mnt/mqm:Z", labelled)
        self.assertIn("bergenlab:ro,Z", labelled)
        self.assertNotIn(":Z", plain)

    def test_generated_vars_preserve_vault_reference(self):
        text = render((ROLE / "templates/mq-lab.local.yml.j2").read_text())
        data = yaml.safe_load(text)
        self.assertEqual(data["mq_rest_password"], "{{ vault_mq_lab_admin_password }}")
        self.assertEqual(data["mq_rest_endpoint"], "https://192.0.2.10:9443/ibmmq/rest/v3")
        self.assertFalse(data["mq_allow_deletion"])

    def test_generated_quadlet_not_enabled_with_systemctl(self):
        tasks = yaml.safe_load((ROLE / "tasks/service.yml").read_text())
        for task in tasks:
            if "ansible.builtin.systemd_service" in task:
                self.assertNotIn("enabled", task["ansible.builtin.systemd_service"])

    def test_secrets_are_protected_and_not_command_line_values(self):
        tasks = yaml.safe_load((ROLE / "tasks/secrets.yml").read_text())
        for task in tasks:
            self.assertTrue(task["no_log"])
            if "ansible.builtin.command" in task:
                for arg in task["ansible.builtin.command"]["argv"]:
                    self.assertNotIn("mq_lab_admin_password", arg)
                    self.assertNotIn("mq_lab_app_password", arg)

    def test_ca_transfer_is_ssh_fetch_not_insecure_https(self):
        tasks = yaml.safe_load((ROLE / "tasks/api.yml").read_text())
        self.assertTrue(any("ansible.builtin.fetch" in t for t in tasks))
        uri = next(t["ansible.builtin.uri"] for t in tasks if "ansible.builtin.uri" in t)
        self.assertTrue(uri["validate_certs"])
        self.assertFalse(uri["use_proxy"])

    def test_runtime_features_preserve_unrelated_flags(self):
        flags = ["mount=nfs", "fuse=1", "nesting=0", "keyctl=0"]
        # Equivalent to the declared role filter; no global feature replacement.
        merged = [f for f in flags if not f.startswith(("nesting=", "keyctl="))] + ["nesting=1", "keyctl=1"]
        self.assertEqual(merged, ["mount=nfs", "fuse=1", "nesting=1", "keyctl=1"])
        text = (ROOT / "ansible/playbooks/configure-mq-lxc-runtime.yml").read_text()
        self.assertIn("reject('match', '^(nesting|keyctl)=')", text)

    def test_production_license_warning_is_explicit(self):
        for path in [ROOT / "docs/MQ-LAB.md", ROLE / "README.md", ROOT / "ansible/group_vars/all/bergen-mq-lab.yml.example"]:
            text = path.read_text()
            self.assertIn("IBM", text)
            self.assertTrue("evaluation" in text.lower() or "evaluation" in text)
            self.assertIn("productive", text.lower())


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for certificate tests")
class CertificateContracts(unittest.TestCase):
    def test_role_openssl_commands_generate_valid_distinct_ca_and_ip_certificate(self):
        tasks = yaml.safe_load((ROLE / "tasks/tls.yml").read_text())
        with tempfile.TemporaryDirectory(prefix="bergen-mq-cert-test-") as directory:
            base = Path(directory)
            (base / "private").mkdir(mode=0o700)
            (base / "tls").mkdir(mode=0o750)
            for task in tasks:
                if task["name"] == "Render evaluation certificate extensions":
                    text = render(task["ansible.builtin.copy"]["content"])
                    (base / "private/server.ext").write_text(text)
                command = task.get("ansible.builtin.command")
                if not command or task["name"] in {"Verify reserved current address is in certificate", "Reject expiring evaluation certificate"}:
                    continue
                args = [render(str(arg)).replace("/etc/bergen-mq-lab", directory) for arg in command["argv"]]
                result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, task["name"] + ": " + result.stderr)
            ssl.create_default_context(cafile=str(base / "ca.crt"))
            for address, valid in [("192.0.2.10", True), ("127.0.0.1", True), ("192.0.2.11", False)]:
                result = subprocess.run(["openssl", "verify", "-CAfile", str(base / "ca.crt"), "-verify_ip", address, str(base / "tls/tls.crt")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode == 0, valid)
            cert = ssl._ssl._test_decode_cert(str(base / "tls/tls.crt"))
            self.assertNotEqual(cert["subject"], cert["issuer"])
            self.assertIn(("DNS", "bergen-mq-lab"), cert["subjectAltName"])


if __name__ == "__main__":
    unittest.main()
