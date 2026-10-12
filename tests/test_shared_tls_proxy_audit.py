"""Offline contracts for optional shared Mail TLS -> internal proxy auditing."""
from datetime import datetime, timezone
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import mail_tls_sync as mail  # noqa: E402
import tls_proxy_target as proxy  # noqa: E402


def topology():
    source = {"mail_tls_required_san": "*.example.invalid"}
    config = {
        "lxc_hostname": "example-proxy",
        "pve_inventory_host": "pve",
        "lxc_vmid": 999,
        "lxc_inventory_group": "reverse_proxy_nodes",
        "reverse_proxy_sites": [{"hostname": "paperless.example.invalid"}],
        "reverse_proxy_tls_cert_path": "/etc/nginx/tls/fullchain.pem",
        "reverse_proxy_tls_key_path": "/etc/nginx/tls/privkey.pem",
    }
    local = {"reverse_proxy_nodes": {"hosts": {"example-proxy": {
        "ansible_host": "192.0.2.44", "ansible_user": "root",
        "ansible_port": 22,
        "ansible_ssh_common_args": (
            '-o ProxyCommand="python3 ./ansible/scripts/pct_ssh_proxy.py '
            '--pve-host 192.0.2.10 --vmid 999" '
            '-o HostKeyAlias=lxc-999 -o StrictHostKeyChecking=yes'),
    }}}}
    shared = {"proxmox_hosts": {"hosts": {
        "pve": {"ansible_host": "192.0.2.10"}
    }}}
    return source, config, local, shared


class SharedProxyAuditTests(unittest.TestCase):
    def test_validates_exact_trusted_pve_transport(self):
        self.assertEqual(proxy.checked_target(*topology()),
                         ("192.0.2.44", "192.0.2.10", 999,
                          ["paperless.example.invalid"]))

    def test_rejects_wrong_vmid_and_unsafe_target(self):
        src, cfg, local, shared = topology()
        cfg["lxc_vmid"] = 998
        with self.assertRaises(proxy.ProxyAuditError):
            proxy.checked_target(src, cfg, local, shared)
        src, cfg, local, shared = topology()
        local["reverse_proxy_nodes"]["hosts"]["example-proxy"]["ansible_ssh_common_args"] = ""
        with self.assertRaises(proxy.ProxyAuditError):
            proxy.checked_target(src, cfg, local, shared)
        src, cfg, local, shared = topology()
        cfg["reverse_proxy_sites"][0]["hostname"] = "deep.sub.example.invalid"
        with self.assertRaises(proxy.ProxyAuditError):
            proxy.checked_target(src, cfg, local, shared)

    def test_refuses_partial_existing_tls_material(self):
        src, cfg, local, shared = topology()
        with patch.object(proxy, "load_restricted_yaml", return_value=cfg), \
             patch.object(proxy, "inventory_children", side_effect=[local, shared]), \
             patch.object(proxy, "checked_remote",
                          return_value='{"cert": true, "key": false}'):
            with self.assertRaisesRegex(proxy.ProxyAuditError, "Partial"):
                proxy.audit_proxy_target(src, "a"*64,
                                         datetime(2026, 12, 22, tzinfo=timezone.utc),
                                         "ignored.yml", "local.yml", "inventory.yml")

    def test_missing_both_is_readonly_first_install_candidate(self):
        src, cfg, local, shared = topology()
        with patch.object(proxy, "load_restricted_yaml", return_value=cfg), \
             patch.object(proxy, "inventory_children", side_effect=[local, shared]), \
             patch.object(proxy, "checked_remote",
                          return_value='{"cert": false, "key": false}'):
            result = proxy.audit_proxy_target(
                src, "a"*64,
                datetime(2026, 12, 22, tzinfo=timezone.utc),
                "ignored.yml", "local.yml", "inventory.yml")
        self.assertEqual(result, "MISSING_EXPECTED_FIRST_INSTALL")

    def test_apply_with_proxy_opts_refused_before_any_ssh_or_file_load(self):
        with patch.object(sys, "argv", ["mail_tls_sync.py", "--config",
                                        "unused.yml", "--proxy-vars",
                                        "proxy.yml", "--apply"]), \
             patch.object(mail, "load_config", side_effect=AssertionError("should not load")):
            with self.assertRaisesRegex(mail.SyncError, "AUDIT ONLY"):
                mail.main()

    def test_existing_no_option_path_keeps_mail_no_change(self):
        cfg = {
            "mail_tls_source_address": "mx.example.invalid",
            "mail_tls_source_ssh_user": "operator",
            "mail_tls_target_inventory_host": "mail",
            "mail_tls_expected_fqdn": "mail.example.invalid",
            "mail_tls_target_cert_file": "/etc/ssl/certs/mail.pem",
            "mail_tls_target_key_file": "/etc/ssl/private/mail.pem",
        }
        now = datetime(2026, 12, 22, tzinfo=timezone.utc)
        with patch.object(sys, "argv", ["mail_tls_sync.py", "--config", "unused.yml"]), \
             patch.object(mail, "load_config", return_value=cfg), \
             patch.object(mail, "source_evidence", return_value=("a"*64, now)), \
             patch.object(mail, "target_evidence", return_value=("a"*64, now)), \
             patch.object(mail, "run_remote_script", return_value="ALL_TLS_PASS"), \
             patch.object(mail, "reused_ssh_connections") as pool:
            pool.return_value.__enter__.return_value = None
            mail.main()

    def test_successful_existing_mail_rotation_keeps_return_contract(self):
        from types import SimpleNamespace
        cfg = {
            "mail_tls_source_cert_file": "/etc/letsencrypt/live/example.invalid/fullchain.pem",
            "mail_tls_source_key_file": "/etc/letsencrypt/live/example.invalid/privkey.pem",
            "mail_tls_expected_fqdn": "mail.example.invalid",
            "mail_tls_target_cert_file": "/etc/ssl/certs/mail.pem",
            "mail_tls_target_key_file": "/etc/ssl/private/mail.pem",
        }
        old = datetime(2026, 10, 1, tzinfo=timezone.utc)
        new = datetime(2026, 12, 22, tzinfo=timezone.utc)
        stage = "/etc/ssl/private/.mail-tls-stage.A1B2C3D4"
        with patch.object(mail, "source_evidence", return_value=("b"*64, new)), \
             patch.object(mail, "target_evidence", return_value=("a"*64, old)), \
             patch.object(mail, "ssh_run", return_value=stage), \
             patch.object(mail, "stage_transfer") as transfer, \
             patch.object(mail, "run_remote_script", return_value="ROTATED"):
            evidence = mail.perform_sync(
                cfg, SimpleNamespace(apply=True), "source", "operator", "target", "root")
        self.assertEqual(evidence, ("b"*64, new))
        self.assertEqual(transfer.call_count, 2)

    def test_proxy_adapter_never_transfers_secrets_or_modifies_mail_timer(self):
        text = (ROOT / "scripts/tls_proxy_target.py").read_text()
        for name in ("subprocess.run", "StrictHostKeyChecking", "HostKeyAlias",
                     "pct_ssh_proxy.py", "AUDIT_ONLY"):
            self.assertIn(name, text)
        for forbidden in ("mail_tls_remote_activate.sh", "systemctl reload nginx",
                          "systemctl stop postfix", "BEGIN PRIVATE KEY",
                          "192.168.", "thebergens.net"):
            self.assertNotIn(forbidden, text)
        entry = (ROOT / "scripts/mail_tls_sync.py").read_text()
        self.assertIn("if args.proxy_vars is not None and args.apply:", entry)
        self.assertIn("perform_sync(", entry)


if __name__ == "__main__":
    unittest.main()
