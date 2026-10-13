"""Fail-closed tests for the staged proxy TLS installer."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import proxy_tls_first_install as installer


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
            patch.object(installer, "reviewed_target", return_value=(["ssh"], {})), \
            patch.object(installer.mail, "source_evidence", return_value=("a"*64, None)), \
            patch.object(installer, "preflight") as preflight, \
            patch.object(installer, "run_actor", side_effect=AssertionError("wrote")), \
            patch.object(installer, "transfer_secret", side_effect=AssertionError("transferred")):
            installer.main()
            preflight.assert_called_once()


if __name__ == "__main__":
    unittest.main()
