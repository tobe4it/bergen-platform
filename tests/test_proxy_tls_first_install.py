"""Fail-closed tests for the staged proxy TLS installer."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import proxy_tls_first_install as installer
import proxy_tls_first_install_remote as remote


class ProxyTLSFirstInstallTests(unittest.TestCase):
    def test_apply_requires_exact_approval_before_reading_config(self):
        cases = [
            ["--apply"],
            ["--apply", "--approval", "NO"],
            ["--approval", installer.APPROVAL],
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                with patch.object(sys, "argv", [
                    "proxy_tls_first_install.py",
                    "--config", "missing.yml",
                    "--proxy-vars", "missing-proxy.yml", *extra,
                ]):
                    with patch.object(installer.mail, "load_config",
                                      side_effect=AssertionError("unsafe read")):
                        with self.assertRaises(installer.FirstInstallError):
                            installer.main()

    def test_bad_stage_paths_are_rejected(self):
        for value in [
            "/tmp/first-install-abcdefg",
            "/etc/nginx/tls/.first-install-abcdef/../x",
            "/etc/nginx/tls/fullchain.pem",
        ]:
            with self.subTest(value=value):
                with self.assertRaises(installer.FirstInstallError):
                    installer.restricted_stage(value)

    def test_read_only_plan_never_opens_stage(self):
        cfg = {
            "mail_tls_source_address": "source.example.invalid",
            "mail_tls_source_ssh_user": "operator",
        }
        with patch.object(sys, "argv", [
            "proxy_tls_first_install.py", "--config", "conf.yml",
            "--proxy-vars", "proxy.yml",
        ]), patch.object(installer.mail, "load_config", return_value=cfg), \
            patch.object(installer.mail, "reused_ssh_connections") as pool, \
            patch.object(installer, "reviewed_target", return_value=(["ssh"], {})), \
            patch.object(installer.mail, "source_evidence", return_value=("a"*64, None)), \
            patch.object(installer, "preflight") as preflight, \
            patch.object(installer, "run_actor", side_effect=AssertionError("wrote")), \
            patch.object(installer, "transfer_secret", side_effect=AssertionError("transferred")):
            installer.main()
            preflight.assert_called_once()
            pool.assert_called_once_with((("operator", "source.example.invalid"),))


    def test_apply_refuses_when_preflight_fails_before_staging(self):
        cfg = {
            "mail_tls_source_address": "source.example.invalid",
            "mail_tls_source_ssh_user": "operator",
        }
        args = [
            "proxy_tls_first_install.py", "--config", "conf.yml",
            "--proxy-vars", "proxy.yml",
            "--apply", "--approval", installer.APPROVAL,
        ]
        with patch.object(sys, "argv", args), \
            patch.object(installer.mail, "load_config", return_value=cfg), \
            patch.object(installer.mail, "reused_ssh_connections"), \
            patch.object(installer, "reviewed_target", return_value=(["ssh"], {})), \
            patch.object(installer.mail, "source_evidence", return_value=("a"*64, None)), \
            patch.object(installer, "preflight",
                         side_effect=installer.FirstInstallError("failed")), \
            patch.object(installer, "run_actor",
                         side_effect=AssertionError("must never stage")):
            with self.assertRaises(installer.FirstInstallError):
                installer.main()

    def test_failed_transfer_attempts_cleanup_without_activation(self):
        cfg = {
            "mail_tls_source_address": "source.example.invalid",
            "mail_tls_source_ssh_user": "operator",
            "mail_tls_source_cert_file": "/safe/cert",
            "mail_tls_source_key_file": "/safe/key",
        }
        args = [
            "proxy_tls_first_install.py", "--config", "conf.yml",
            "--proxy-vars", "proxy.yml",
            "--apply", "--approval", installer.APPROVAL,
        ]
        stage = "/etc/nginx/tls/.first-install-ABCDEFGH"
        def actor(_ssh, operation):
            if operation == ["stage"]:
                return stage
            if operation == ["cleanup", stage]:
                return "PROXY_TLS_STAGE_CLEANED"
            raise AssertionError("must not activate after transfer failure")
        with patch.object(sys, "argv", args), \
            patch.object(installer.mail, "load_config", return_value=cfg), \
            patch.object(installer.mail, "reused_ssh_connections"), \
            patch.object(installer, "reviewed_target", return_value=(["ssh"], {})), \
            patch.object(installer.mail, "source_evidence", return_value=("a"*64, None)), \
            patch.object(installer, "preflight"), \
            patch.object(installer, "run_actor", side_effect=actor) as staged, \
            patch.object(installer, "transfer_secret",
                         side_effect=installer.FirstInstallError("transfer failed")):
            with self.assertRaises(installer.FirstInstallError):
                installer.main()
            self.assertEqual(staged.call_count, 2)

    def test_remote_refuses_existing_or_symlinked_destinations(self):
        with tempfile.TemporaryDirectory() as d:
            cert = Path(d) / "cert.pem"
            key = Path(d) / "key.pem"
            with patch.object(remote, "CERT", cert), patch.object(remote, "KEY", key):
                cert.write_bytes(b"already exists")
                with self.assertRaises(RuntimeError):
                    remote.must_be_absent()
                cert.unlink()
                cert.symlink_to(key)
                with self.assertRaises(RuntimeError):
                    remote.must_be_absent()

    def test_remote_partial_install_rolls_back_first_file(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            stage = base / "stage"
            stage.mkdir()
            (stage / "fullchain.pem").write_bytes(b"certificate bytes")
            (stage / "privkey.pem").write_bytes(b"private key bytes")
            cert = base / "installed-cert.pem"
            key = base / "installed-key.pem"
            original_link = os.link
            def second_link_fails(source, destination, **kwargs):
                if destination == key:
                    raise PermissionError("simulated second link failure")
                return original_link(source, destination, **kwargs)
            with patch.object(remote, "CERT", cert), \
                patch.object(remote, "KEY", key), \
                patch.object(remote, "refuse_active_nginx"), \
                patch.object(remote, "checked_stage", return_value=stage), \
                patch.object(remote, "validate"), \
                patch.object(remote.os, "link", side_effect=second_link_fails):
                with self.assertRaises(PermissionError):
                    remote.activate(str(stage), "a"*64, installer.SITE)
                self.assertFalse(cert.exists())
                self.assertFalse(key.exists())

    def test_remote_cleanup_rejects_unexpected_stage_entries(self):
        with tempfile.TemporaryDirectory() as d:
            stage = Path(d)
            (stage / "surprise.txt").write_text("nothing sensitive")
            with patch.object(remote, "checked_stage", return_value=stage):
                with self.assertRaises(RuntimeError):
                    remote.cleanup(str(stage))
            self.assertTrue((stage / "surprise.txt").exists())

    def test_actor_error_does_not_expose_remote_stderr(self):
        result = type("Result", (), {
            "returncode": 1,
            "stdout": b"SECRET_MARKER",
            "stderr": b"SECRET_MARKER",
        })()
        with patch.object(installer.subprocess, "run", return_value=result):
            with self.assertRaises(installer.FirstInstallError) as caught:
                installer.run_actor(["ssh"], ["stage"])
        self.assertNotIn("SECRET_MARKER", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
