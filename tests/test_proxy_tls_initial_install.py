"""Offline tests: guarded Certbot TLS first install into isolated proxy."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/proxy_tls_initial_install.py"
REMOTE = ROOT / "scripts/proxy_tls_remote_initial_activate.py"
spec = importlib.util.spec_from_file_location("proxy_tls_initial_install", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def fixtures():
    return (
        {
            "mail_tls_source_address": "mx.example.invalid",
            "mail_tls_source_ssh_user": "operator",
            "mail_tls_source_cert_file": "/etc/letsencrypt/live/example.invalid/fullchain.pem",
            "mail_tls_source_key_file": "/etc/letsencrypt/live/example.invalid/privkey.pem",
            "mail_tls_required_san": "*.example.invalid",
        },
        {
            "lxc_hostname": "example-proxy", "pve_inventory_host": "pve",
            "lxc_vmid": 999, "lxc_inventory_group": "reverse_proxy_nodes",
            "reverse_proxy_tls_cert_path": "/etc/nginx/tls/fullchain.pem",
            "reverse_proxy_tls_key_path": "/etc/nginx/tls/privkey.pem",
            "reverse_proxy_sites": [{"hostname": "paperless.example.invalid"}],
        },
        {"proxmox_hosts": {"hosts": {"pve": {"ansible_host": "192.0.2.1"}}}},
        {"reverse_proxy_nodes": {"hosts": {"example-proxy": {
            "ansible_host": "192.0.2.3", "ansible_user": "root", "ansible_port": 22,
            "ansible_ssh_common_args": (
                '-o ProxyCommand="python3 ./ansible/scripts/pct_ssh_proxy.py '
                '--pve-host 192.0.2.1 --vmid 999" '
                '-o HostKeyAlias=lxc-999 -o StrictHostKeyChecking=yes'),
        }}}},
    )


class ProxyTlsFirstInstall(unittest.TestCase):
    def test_expected_target_and_wildcard(self):
        self.assertEqual(sync.validate(*fixtures()), (
            "192.0.2.1", "192.0.2.3", ["paperless.example.invalid"]))

    def test_vmid_transport_group_and_site_guard(self):
        s, p, i, l = fixtures()
        p["lxc_vmid"] = 998
        with self.assertRaisesRegex(sync.InstallError, "transport"):
            sync.validate(s, p, i, l)
        s, p, i, l = fixtures()
        l["reverse_proxy_nodes"]["hosts"]["example-proxy"]["ansible_ssh_common_args"] = ""
        with self.assertRaisesRegex(sync.InstallError, "transport"):
            sync.validate(s, p, i, l)
        s, p, i, l = fixtures()
        l["reverse_proxy_nodes"]["hosts"]["extra"] = {}
        with self.assertRaisesRegex(sync.InstallError, "exactly"):
            sync.validate(s, p, i, l)
        s, p, i, l = fixtures()
        p["reverse_proxy_sites"][0]["hostname"] = "a.b.example.invalid"
        with self.assertRaisesRegex(sync.InstallError, "outside"):
            sync.validate(s, p, i, l)

    def test_reject_unreviewed_tls_key_path(self):
        s, p, i, l = fixtures()
        p["reverse_proxy_tls_key_path"] = "/tmp/privkey.pem"
        with self.assertRaisesRegex(sync.InstallError, "reviewed"):
            sync.validate(s, p, i, l)

    def test_requires_private_local_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "source.yml"
            file.write_text(yaml.safe_dump(fixtures()[0]))
            file.chmod(0o644)
            with self.assertRaisesRegex(sync.InstallError, "mode 0600"):
                sync.load_private_yaml(file)
            file.chmod(0o600)
            self.assertEqual(sync.load_private_yaml(file), fixtures()[0])

    def test_read_only_does_not_invoke_install(self):
        source, proxy, inventory, local = fixtures()
        with tempfile.TemporaryDirectory() as td:
            paths = [Path(td) / name for name in (
                "source.yml", "proxy.yml", "inventory.yml", "local.yml")]
            for path, val in zip(paths, [
                source, proxy, {"all": {"children": inventory}},
                {"all": {"children": local}}]):
                path.write_text(yaml.safe_dump(val))
                path.chmod(0o600)
            with patch.object(sync, "proxy_ssh", return_value=["ssh", "root@192.0.2.3"]), \
                 patch.object(sync, "source_evidence", return_value=("a"*64, "notAfter=Jan 1 00:00:00 2027 GMT")), \
                 patch.object(sync, "ensure_empty") as guard, \
                 patch.object(sync, "install", side_effect=AssertionError("unexpected install")):
                sync.main(["--source-vars", str(paths[0]),
                           "--proxy-vars", str(paths[1]),
                           "--inventory", str(paths[2]),
                           "--local-inventory", str(paths[3])])
                guard.assert_called_once()

    def test_pinned_ssh_chain_and_no_nginx_start(self):
        args = sync.proxy_ssh("192.0.2.3", "192.0.2.1", 999, SCRIPT)
        joined = " ".join(args)
        for expected in ("StrictHostKeyChecking=yes", "HostKeyAlias=lxc-999",
                         "--pve-host 192.0.2.1 --vmid 999", "BatchMode=yes",
                         "ForwardAgent=no"):
            self.assertIn(expected, joined)
        controller = SCRIPT.read_text()
        remote = REMOTE.read_text()
        for expected in ("stdout=subprocess.PIPE", "stdin=upstream.stdout",
                         "stderr=subprocess.DEVNULL", "if not args.apply:",
                         "test ! -x /usr/sbin/nginx"):
            self.assertIn(expected, controller)
        for expected in ("os.replace(cert, final_cert)", "os.replace(key, final_key)",
                         "sslserver", "os.path.lexists", "Nginx already installed"):
            self.assertIn(expected, remote)
        self.assertNotIn("systemctl start nginx", remote)
        self.assertNotIn("systemctl reload nginx", remote)

    def test_no_site_specific_values(self):
        for path in (SCRIPT, REMOTE, ROOT / "docs/PROXY-TLS-INITIAL-INSTALL.md"):
            content = path.read_text()
            self.assertNotIn("thebergens.net", content)
            self.assertNotIn("192.168.", content)


if __name__ == "__main__":
    unittest.main()
