"""Offline tests for the staged Bergen Paperless LDAPS TLS probe."""
import importlib.util
from pathlib import Path
import ssl
import unittest
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "ansible/scripts/paperless_ldap_tls_preflight.py"
)
spec = importlib.util.spec_from_file_location("paperless_ldap_tls_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def getpeercert(self):
        return {"subjectAltName": (("DNS", probe.HOST),)}

    def version(self):
        return "TLSv1.3"


class FakeContext:
    def __init__(self):
        self.check_hostname = False
        self.verify_mode = ssl.CERT_NONE
        self.minimum_version = None
        self.server_hostname = None

    def wrap_socket(self, conn, *, server_hostname):
        self.server_hostname = server_hostname
        return FakeConn()


class PaperlessLDAPPreflightTests(unittest.TestCase):
    def test_exact_host_and_strict_tls_validation(self):
        self.assertEqual(probe.HOST, "ldap.thebergens.net")
        self.assertEqual(probe.PORT, 636)
        context = FakeContext()
        with patch.object(probe.ssl, "create_default_context", return_value=context) as create, patch.object(
            probe.socket, "create_connection", return_value=FakeConn()
        ) as connect:
            self.assertEqual(probe.verify_ldaps(), "TLSv1.3")
        create.assert_called_once_with(cafile=None)
        connect.assert_called_once_with(("ldap.thebergens.net", 636), timeout=10)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.server_hostname, probe.HOST)

    def test_missing_certificate_fails(self):
        class EmptyCert(FakeConn):
            def getpeercert(self):
                return None

        context = FakeContext()
        context.wrap_socket = lambda *_args, **_kwargs: EmptyCert()
        with patch.object(probe.ssl, "create_default_context", return_value=context), patch.object(
            probe.socket, "create_connection", return_value=FakeConn()
        ):
            with self.assertRaises(ssl.SSLError):
                probe.verify_ldaps()


if __name__ == "__main__":
    unittest.main()
