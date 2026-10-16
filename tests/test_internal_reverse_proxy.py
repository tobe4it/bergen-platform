"""Static deployment-safety contracts for the reusable internal Nginx role."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/nginx_reverse_proxy"
BOOTSTRAP = ROOT / "ansible/playbooks/bootstrap-reverse-proxy.yml"


class InternalReverseProxyContracts(unittest.TestCase):
    def tasks(self, name):
        return yaml.safe_load((ROLE / "tasks" / name).read_text())

    def test_explicit_approval_and_no_unsafe_allow_all(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertFalse(defaults["reverse_proxy_deployment_approved"])
        self.assertTrue(defaults["reverse_proxy_internal_only"])
        self.assertEqual(defaults["reverse_proxy_allow_cidrs"], [])
        preflight = str(self.tasks("preflight.yml"))
        self.assertIn("'0.0.0.0/0' not in reverse_proxy_allow_cidrs", preflight)
        self.assertIn("'::/0' not in reverse_proxy_allow_cidrs", preflight)
        self.assertIn("openssl", preflight)
        self.assertIn("reverse_proxy_private_pubkey", preflight)

    def test_package_install_cannot_start_before_tls_validation(self):
        sequence = self.tasks("main.yml")
        self.assertEqual(sequence[0]["ansible.builtin.import_tasks"], "preflight.yml")
        self.assertEqual(sequence[1]["ansible.builtin.import_tasks"], "install.yml")
        apt = next(t["ansible.builtin.apt"] for t in self.tasks("install.yml")
                   if "ansible.builtin.apt" in t)
        self.assertEqual(apt["policy_rc_d"], 101)
        validating = self.tasks("validate.yml")
        self.assertEqual(validating[0]["ansible.builtin.command"]["argv"], ["nginx", "-t"])

    def test_deployment_restricted_to_dedicated_container_group(self):
        plays = yaml.safe_load(BOOTSTRAP.read_text())
        checks = str(plays[0]["tasks"][0]["ansible.builtin.assert"]["that"])
        self.assertIn("reverse_proxy_nodes", checks)
        self.assertIn("ansible_virtualization_type", checks)
        self.assertIn("reverse_proxy_deployment_approved", checks)

    def test_template_is_tls_only_and_prevents_client_forwarded_ip_spoofing(self):
        text = (ROLE / "templates/internal-proxy-site.conf.j2").read_text()
        self.assertIn("listen 443 ssl;", text)
        self.assertNotIn("listen 80", text)
        self.assertIn("deny all;", text)
        self.assertIn("X-Forwarded-For $remote_addr;", text)
        self.assertNotIn("$proxy_add_x_forwarded_for", text)

    def test_public_templates_have_no_real_site_secrets(self):
        for path in ROLE.rglob("*"):
            if path.is_file():
                txt = path.read_text()
                self.assertNotIn("site-specific.invalid", txt)
                self.assertNotIn("BEGIN PRIVATE KEY", txt)


if __name__ == "__main__":
    unittest.main()
