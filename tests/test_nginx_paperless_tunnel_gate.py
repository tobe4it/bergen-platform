"""Offline regression checks for Nginx Paperless backend approval gates."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "ansible/roles/nginx_reverse_proxy/tasks/preflight.yml"
SITE = ROOT / "ansible/roles/nginx_reverse_proxy/templates/internal-proxy-site.conf.j2"


class NginxPaperlessTunnelGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = yaml.safe_load(PREFLIGHT.read_text(encoding="utf-8"))
        cls.site = SITE.read_text(encoding="utf-8")

    def test_refuses_test_net_documentation_addresses(self):
        task = next(t for t in self.tasks if t["name"].startswith("Refuse documentation-only backend"))
        condition = task["ansible.builtin.assert"]["that"][0]
        regex = re.search(r"is not match\('([^']+)'\)", condition).group(1)
        for ip in ("192.0.2.10", "198.51.100.22", "203.0.113.5"):
            self.assertIsNotNone(re.match(regex, "http://" + ip + ":8000"))
        for real in ("http://127.0.0.1:18000", "http://192.168.2.5:80"):
            self.assertIsNone(re.match(regex, real))

    def test_exact_paperless_backend_and_hostname_guard(self):
        task = next(t for t in self.tasks if t["name"].startswith("Require the reviewed Paperless"))
        self.assertIn("item.backend_url == 'http://127.0.0.1:18000'",
                      task["ansible.builtin.assert"]["that"])
        self.assertEqual(task["when"], "item.hostname | default('') == 'paperless.thebergens.net'")

    def test_nginx_still_restricts_client_addresses(self):
        all_raw = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("reverse_proxy_allow_cidrs | length > 0", all_raw)
        self.assertIn("'0.0.0.0/0' not in reverse_proxy_allow_cidrs", all_raw)
        self.assertIn("'::/0' not in reverse_proxy_allow_cidrs", all_raw)
        self.assertIn("allow {{ cidr }};", self.site)
        self.assertIn("deny all;", self.site)
        self.assertIn("proxy_pass {{ item.backend_url }};", self.site)


if __name__ == "__main__":
    unittest.main()
