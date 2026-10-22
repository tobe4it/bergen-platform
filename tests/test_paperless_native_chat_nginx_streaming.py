"""Offline safety regression checks for the isolated Paperless chat Nginx patch."""
import ast
from pathlib import Path
import runpy
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/repair_native_chat_nginx.py"
PLAY = ROOT / "ansible/playbooks/repair-paperless-native-chat-nginx.yml"
SITE = ROOT / "ansible/roles/nginx_reverse_proxy/templates/internal-proxy-site.conf.j2"

SAMPLE = """# Managed by Ansible: paperless.thebergens.net
server {
    listen 443 ssl;
    server_name paperless.thebergens.net;

    ssl_certificate /etc/nginx/tls/fullchain.pem;
    ssl_certificate_key /etc/nginx/tls/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    proxy_read_timeout 120s;
    allow 192.168.0.0/24;
    deny all;

    location / {
        proxy_pass http://127.0.0.1:18000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $reverse_proxy_connection_upgrade;
    }
}
"""


class TestPaperlessChatProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = SCRIPT.read_text()
        ast.parse(cls.code)
        cls.module = runpy.run_path(str(SCRIPT))

    def test_exact_location_is_safely_additive_and_idempotent(self):
        candidate = self.module["candidate"]
        fragment = self.module["LOCATION"]
        out, already = candidate(SAMPLE)
        self.assertFalse(already)
        self.assertEqual(out.replace(fragment, "", 1), SAMPLE)
        self.assertEqual(out.count("location = /api/documents/chat/"), 1)
        self.assertIn("proxy_read_timeout 300s;", out)
        self.assertIn("proxy_buffering off;", out)
        self.assertIn("proxy_read_timeout 120s;", out)
        self.assertIn("    deny all;", out)
        self.assertEqual(out.count("proxy_set_header X-Forwarded-Proto $scheme;"), 2)
        out2, already2 = candidate(out)
        self.assertTrue(already2)
        self.assertEqual(out2, out)

    def test_only_reviewed_exact_proxy_can_be_patched(self):
        candidate = self.module["candidate"]
        invalid = [
            SAMPLE.replace("paperless.thebergens.net", "ai.thebergens.net"),
            SAMPLE.replace("127.0.0.1:18000", "127.0.0.1:13000"),
            SAMPLE.replace("    deny all;", "    allow all;"),
            SAMPLE.replace("    proxy_read_timeout 120s;", "    proxy_read_timeout 900s;"),
            SAMPLE + "\nlocation /admin/ { }\n",
            SAMPLE.replace("ssl_certificate_key ", "unrecognized_key "),
        ]
        for bad in invalid:
            with self.subTest(bad=bad[-65:]):
                with self.assertRaises(self.module["Refusal"]):
                    candidate(bad)

    def test_main_requires_mode_fingerprint_and_approval(self):
        src = self.code
        for token in (
            'VHOST.is_symlink()',
            'VHOST.resolve(strict=True) == EXPECTED_DEST',
            'st.st_uid == 0 and st.st_gid == 0',
            'fingerprint == expected',
            '"BASELINE_SHA_DRIFT"',
            '"NGINX_BASELINE_BAD"',
            '"NGINX_RELOAD_FAILED"',
            '"ROLLBACK_UNVERIFIED"',
            '"APPLY_FAILED_ROLLED_BACK"',
            'write_atomic(old_bytes, old_stat)',
            'command_ok(["nginx", "-t"])',
            'command_ok(["systemctl", "reload", "nginx"])',
            'if __name__ == "__main__":',
        ):
            self.assertIn(token, src)
        self.assertNotIn("shell=True", src)

    def test_playbook_gates_apply_and_suppresses_raw_output(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertIn("default('audit')", play["vars"]["bp_chat_proxy_mode"])
        checks = str(play["tasks"][0]["ansible.builtin.assert"]["that"])
        self.assertIn("paperless_chat_proxy_apply_approved", checks)
        self.assertIn("bp_chat_proxy_expected_sha", checks)
        self.assertIn("not ansible_check_mode", checks)
        commands = [t for t in play["tasks"] if t.get("ansible.builtin.command")]
        self.assertEqual(len(commands), 3)
        self.assertTrue(all(x.get("no_log") for x in commands))
        patch = next(t for t in commands if t["name"].startswith("Perform separately"))
        self.assertEqual(patch["when"], "bp_chat_proxy_apply")
        self.assertIn("'125'", str(patch["ansible.builtin.command"]["argv"]))

    def test_role_template_scopes_only_native_chat_opt_in(self):
        tpl = SITE.read_text()
        self.assertIn("item.hostname == 'paperless.thebergens.net'", tpl)
        self.assertIn("item.native_chat_streaming | default(false) | bool", tpl)
        self.assertEqual(tpl.count("location = /api/documents/chat/"), 1)
        self.assertEqual(tpl.count("proxy_buffering off;"), 1)
        self.assertEqual(tpl.count("proxy_read_timeout 300s;"), 1)
        self.assertIn("location / {", tpl)


if __name__ == "__main__":
    unittest.main()
