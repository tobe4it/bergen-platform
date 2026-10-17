"""Offline regressions for SMB2 authorization intents without mutations."""
import ast
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

MODULE = (Path(__file__).resolve().parents[1] /
          "ansible/files/paperless/probe_synology_smb_delete_access.py")
spec = importlib.util.spec_from_file_location("smb_intent", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SMBDeleteIntentTests(unittest.TestCase):
    def test_only_site_root_and_archive_entry_are_targets(self):
        for site in sorted(m.SITE_SHARES):
            self.assertEqual(m.request_plan(site), (
                (".bergen-paperless-archive", 0x10000,
                 "PROTECTED_ENTRY_DELETE"),
                ("", 0x40, "SITE_ROOT_DELETE_CHILD"),
                (".bergen-paperless-archive", 0x01,
                 "PROTECTED_ROOT_ENUMERATION"),
            ))

    def test_disallow_arbitrary_shares_and_users(self):
        for site in ("private", "home", "Familie", "",
                     "../homes", "homes/foo", "paperless-scan/../"):
            with self.subTest(site=site), self.assertRaises(RuntimeError):
                m.validate_site("ldap.thebergens.net", site, "testnormal")
        for user in ("root", "admin", "supervisor", "paperless-sync",
                     "Administrator", "", "a/b", "a\\b", "x y", "-"):
            if user == "-":  # "-" has been ruled out by the username regex.
                continue
            with self.subTest(user=user), self.assertRaises(RuntimeError):
                m.validate_site("ldap.thebergens.net", "paperless-scan", user)
        with self.assertRaises(RuntimeError):
            m.validate_site("bad/host", "paperless-scan", "testnormal")

    def test_denied_is_exact_ntstatus_only(self):
        denied = 0xC0000022
        self.assertEqual(m.classify_smb_result(None, denied), "GRANTED")
        self.assertEqual(
            m.classify_smb_result(SimpleNamespace(status=denied), denied),
            "DENIED")
        for value in (0, 0xC0000034, 0xC0000043, "STATUS_ACCESS_DENIED"):
            with self.subTest(value=value):
                self.assertEqual(
                    m.classify_smb_result(SimpleNamespace(status=value), denied),
                    "INCONCLUSIVE")

    def test_no_mutating_smb2_requests_or_delete_on_close(self):
        code = MODULE.read_text()
        for forbidden in ("FILE_DELETE_ON_CLOSE", "FILE_OVERWRITE_IF",
                          "FILE_OPEN_IF", "FILE_SUPERSEDE",
                          "FILE_CREATE", "FILE_RENAME_INFORMATION",
                          "handle.write(", ".delete(", ".set_info(",
                          "os.unlink(", "os.rename("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)
        self.assertIn("CreateDisposition.FILE_OPEN", code)
        self.assertIn("CreateOptions.FILE_DIRECTORY_FILE", code)
        self.assertIn('getpass.getpass(', code)
        self.assertIn("NO_SMB_MUTATING_REQUESTS_SENT", code)

    def test_real_smb_close_sent_and_pin_checked_before_password_prompt(self):
        code = MODULE.read_text()
        self.assertIn("root.close()", code)
        self.assertIn("handle.close()", code)
        self.assertNotIn("close(False)", code)
        self.assertIn('installed == "1.17.0"', code)
        self.assertLess(code.index("local_api_preflight()", code.index("def execute(")),
                        code.index("getpass.getpass(", code.index("def execute(")))
        self.assertIn("verify_smbprotocol_version()", code)
        self.assertIn("require_encryption=True", code)

    def test_version_gate_missing_and_wrong_version_fails_closed(self):
        from importlib.metadata import PackageNotFoundError
        from unittest.mock import patch
        with patch.object(m, "version", return_value="1.17.0"):
            self.assertEqual(m.verify_smbprotocol_version(), "1.17.0")
        with patch.object(m, "version", return_value="1.16.1"):
            with self.assertRaises(RuntimeError):
                m.verify_smbprotocol_version()
        with patch.object(m, "version", side_effect=PackageNotFoundError):
            with self.assertRaisesRegex(
                    RuntimeError, "SMBPROTOCOL_LIBRARY_UNAVAILABLE"):
                m.verify_smbprotocol_version()

    def test_sanitized_errors_never_expose_credentials_or_paths(self):
        message = ("SMB authentication failed thomas@bergen.intern "
                   "/volume1/homes private password token")
        bad = RuntimeError(message)
        diagnostic = " ".join(m.safe_diagnostic("SESSION_SETUP", bad))
        self.assertEqual(diagnostic,
                         "SMB_PROBE_DIAGNOSTIC SESSION_SETUP VALIDATION NO_STATUS RuntimeError")
        for prohibited in ("thomas", "/volume1", "password", "token"):
            self.assertNotIn(prohibited, diagnostic)
        unknown = " ".join(m.safe_diagnostic(
            "UNTRUSTED/" + message, bad))
        self.assertTrue(unknown.startswith("SMB_PROBE_DIAGNOSTIC PRECHECK "))
        self.assertNotIn("password", unknown)

    def test_sanitized_numeric_ntstatus_retained_without_raw_error(self):
        class SMBResponseException(Exception):
            status = 0xC000006D
        diagnostic = " ".join(m.safe_diagnostic(
            "SESSION_SETUP", SMBResponseException("confidential\n")))
        self.assertEqual(
            diagnostic,
            "SMB_PROBE_DIAGNOSTIC SESSION_SETUP SMB_STATUS 0xC000006D "
            "SMBResponseException")
        self.assertNotIn("confidential", diagnostic)

    def test_local_api_preflight_never_prompts_or_attempts_network(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with patch.object(m, "local_api_preflight", return_value=True):
            with patch.object(m.getpass, "getpass",
                              side_effect=AssertionError("No credentials")):
                with redirect_stdout(output):
                    m.main(["--local-api-check"])
        self.assertEqual(output.getvalue().splitlines(), [
            "SMBPROTOCOL_LOCAL_API_CHECK_OK",
            "NO_SMB_CONNECTION_ATTEMPTED",
        ])
        with self.assertRaises(RuntimeError):
            m.main(["--local-api-check", "--username", "testnormal"])

    def test_tcp_preflight_is_passwordless_and_nonmutating(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace

        class FakeSocket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        output = StringIO()
        with patch.object(m.socket, "create_connection",
                          return_value=FakeSocket()) as connected:
            with patch.object(m.getpass, "getpass",
                              side_effect=AssertionError("No password prompt")):
                with redirect_stdout(output):
                    m.main(["--tcp-preflight",
                            "--server", "ldap.thebergens.net"])
        connected.assert_called_once_with(("ldap.thebergens.net", 445),
                                          timeout=5)
        self.assertEqual(output.getvalue().splitlines(), [
            "SMB_TCP_445_REACHABLE",
            "NO_SMB_AUTHENTICATION_ATTEMPTED",
            "NO_SMB_MUTATING_REQUESTS_SENT",
        ])
        for args in (
            ["--tcp-preflight"],
            ["--tcp-preflight", "--server", "invalid/host"],
            ["--tcp-preflight", "--server", "ldap.thebergens.net",
             "--username", "someuser"],
            ["--tcp-preflight", "--server", "ldap.thebergens.net",
             "--site-share", "homes"],
            ["--local-api-check", "--tcp-preflight"],
        ):
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                m.main(args)

    def test_tcp_failure_redacted_and_blocks_without_smb(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        from io import StringIO
        failure = OSError("SECRET user@domain /private/contents")
        err = StringIO()
        with patch.object(m.socket, "create_connection",
                          side_effect=failure):
            with redirect_stderr(err):
                with self.assertRaisesRegex(
                        RuntimeError, "SMB_TCP_445_NOT_REACHABLE"):
                    m.tcp_preflight("ldap.thebergens.net")
        self.assertIn("SMB_PROBE_DIAGNOSTIC CONNECT_OBJECT TRANSPORT", err.getvalue())
        self.assertNotIn("SECRET", err.getvalue())
        self.assertNotIn("/private/", err.getvalue())

    def test_distinct_connection_construction_and_negotiation_phases(self):
        source = MODULE.read_text()
        self.assertIn('phase = "CONNECT_OBJECT"', source)
        self.assertIn('phase = "SMB_NEGOTIATE"', source)
        self.assertLess(source.index('phase = "CONNECT_OBJECT"'),
                        source.index('phase = "SMB_NEGOTIATE"'))
        self.assertIn("safe_exception_type(error)", source)
        self.assertNotIn("print(str(exc))", source)

    def test_unauthenticated_negotiation_sends_no_creds_and_closes_socket(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from io import StringIO
        states = []
        class FakeConnection:
            def __init__(self, guid, server, port):
                states.append(("constructed", server, port))
            def connect(self, timeout):
                states.append(("negotiated", timeout))
            def disconnect(self, close):
                states.append(("closed", close))
        output = StringIO()
        with patch.object(m, "local_api_preflight", return_value=True):
            with patch.object(m.getpass, "getpass",
                              side_effect=AssertionError("No password prompt")):
                with redirect_stdout(output):
                    m.negotiate_preflight(
                        "ldap.thebergens.net",
                        connection_factory=FakeConnection)
        self.assertEqual(states, [
            ("constructed", "ldap.thebergens.net", 445),
            ("negotiated", 15), ("closed", True),
        ])
        self.assertEqual(output.getvalue().splitlines(), [
            "SMB_DIALECT_NEGOTIATED",
            "NO_SMB_AUTHENTICATION_ATTEMPTED",
            "NO_SMB_MUTATING_REQUESTS_SENT",
        ])

    def test_unauthenticated_negotiation_error_sanitized_and_cleaned(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        from io import StringIO
        states = []
        class BadConnection:
            def __init__(self, guid, server, port):
                pass
            def connect(self, timeout):
                raise RuntimeError("private host SMB negotiate text")
            def disconnect(self, close):
                states.append(("disconnect", close))
        err = StringIO()
        with patch.object(m, "local_api_preflight", return_value=True):
            with redirect_stderr(err):
                with self.assertRaisesRegex(
                        RuntimeError, "SMB_NEGOTIATION_PREFLIGHT_BLOCKED"):
                    m.negotiate_preflight("ldap.thebergens.net",
                                          connection_factory=BadConnection)
        self.assertIn("SMB_PROBE_DIAGNOSTIC SMB_NEGOTIATE VALIDATION",
                      err.getvalue())
        self.assertNotIn("private", err.getvalue())
        self.assertEqual(states, [("disconnect", True)])

    def test_preflight_flags_cannot_trigger_authentication(self):
        from unittest.mock import patch
        calls = []
        with patch.object(m, "negotiate_preflight",
                          side_effect=lambda server, port: calls.append((server, port))):
            with patch.object(m.getpass, "getpass",
                              side_effect=AssertionError("No password")):
                m.main(["--negotiate-preflight", "--server",
                        "ldap.thebergens.net"])
        self.assertEqual(calls, [("ldap.thebergens.net", 445)])
        for args in (
            ["--negotiate-preflight"],
            ["--negotiate-preflight", "--server", "ldap.thebergens.net",
             "--username", "someone"],
            ["--negotiate-preflight", "--server", "ldap.thebergens.net",
             "--site-share", "homes"],
            ["--negotiate-preflight", "--server", "ldap.thebergens.net",
             "--tcp-preflight"],
        ):
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                m.main(args)

    def test_forwarded_smb_port_is_localhost_only(self):
        self.assertEqual(m.validate_endpoint("127.0.0.1", 1445), 1445)
        self.assertEqual(m.validate_endpoint("192.168.6.11", 445), 445)
        for server, port in (
            ("192.168.6.11", 1445),
            ("ldap.thebergens.net", 1445),
            ("0.0.0.0", 1445),
            ("127.0.0.1", 1446),
            ("127.0.0.1", 0),
            ("127.0.0.1", -1),
            ("127.0.0.1", True),
            ("bad/server", 445),
        ):
            with self.subTest(server=server, port=port):
                with self.assertRaises(RuntimeError):
                    m.validate_endpoint(server, port)

    def test_forwarded_tcp_preflight_is_passwordless(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from io import StringIO

        class FakeSocket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with patch.object(m.socket, "create_connection",
                          return_value=FakeSocket()) as connected:
            with patch.object(m.getpass, "getpass",
                              side_effect=AssertionError("No credentials")):
                with redirect_stdout(StringIO()):
                    m.main(["--tcp-preflight", "--server", "127.0.0.1",
                            "--port", "1445"])
        connected.assert_called_once_with(("127.0.0.1", 1445), timeout=5)

    def test_syntax_and_only_documented_probes(self):
        root = ast.parse(MODULE.read_text(), filename=str(MODULE))
        self.assertIsInstance(root, ast.Module)
        self.assertEqual(len(m.request_plan("homes")), 3)
        self.assertEqual(len(m.request_plan("paperless-scan")), 3)


if __name__ == "__main__":
    unittest.main()
