"""No-network synthetic tests for temporary redacted SSH SMB tunnel audit."""
import ast
import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
SOURCE = BASE / "diagnose_synology_ssh_smb_forward.py"
spec = importlib.util.spec_from_file_location("ssh_smb_forward", SOURCE)
m = importlib.util.module_from_spec(spec)
import sys
sys.path.insert(0, str(BASE))
spec.loader.exec_module(m)


class SSHForwardDiagnosticTests(unittest.TestCase):
    def test_only_fixed_sanitized_ssh_channel_labels(self):
        cases = (
            ("channel 1: open failed: administratively prohibited: open failed",
             "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE",
             "SSH_SERVER_TCP_FORWARD_DENIED"),
            ("channel 1: open failed: connect failed: connection refused",
             "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE",
             "SSH_REMOTE_TARGET_CONNECT_FAILED"),
            ("channel 2: open failed: unknown",
             "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE",
             "SSH_CHANNEL_OPEN_FAILED_UNCLASSIFIED"),
            ("channel 1: direct-tcpip: connected to 127.0.0.1",
             "SMB3_02_NEGOTIATED",
             "SSH_FORWARD_SMB3_02_NEGOTIATED"),
            ("channel 1: direct-tcpip: connected to 127.0.0.1",
             "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE",
             "SSH_FORWARD_OPEN_SEEN_SMB_RESET"),
            ("noise",
             "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE",
             "SSH_FORWARD_DIAGNOSTIC_INCONCLUSIVE"),
        )
        for raw, outcome, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(m.classify_forwarding_log(raw, outcome),
                                 expected)

    def test_private_ssh_debug_strings_never_appear_in_verdict(self):
        private = ("supervisor@ldap.thebergens.net "
                   "MY_SSH_PRIVATE_KEY /volume1/homes/Private")
        verdict = m.classify_forwarding_log(
            "channel 1: open failed: administratively prohibited " + private,
            "REMOTE_RESET_BEFORE_NEGOTIATE_RESPONSE")
        self.assertEqual(verdict, "SSH_SERVER_TCP_FORWARD_DENIED")
        for secret in ("supervisor", "PRIVATE", "ldap.", "/volume1"):
            self.assertNotIn(secret, verdict)

    def test_syntax_and_no_nas_side_effects(self):
        code = SOURCE.read_text()
        ast.parse(code, filename=str(SOURCE))
        self.assertIn("TemporaryDirectory", code)
        self.assertIn('"127.0.0.1:1445:127.0.0.1:445"', code)
        self.assertIn('"StrictHostKeyChecking=yes"', code)
        self.assertIn('"ExitOnForwardFailure=yes"', code)
        self.assertIn('"BatchMode=yes"', code)
        self.assertIn('"NumberOfPasswordPrompts=0"', code)
        self.assertIn('"NO_SMB_AUTHENTICATION_ATTEMPTED"', code)
        for forbidden in (
            "os.unlink(", "os.rename(", "os.chmod(", "os.chown(",
            "FILE_DELETE_ON_CLOSE", "getpass", "password=", "print(raw)",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_rejected_host_requires_no_ssh(self):
        with patch.object(m.subprocess, "run",
                          side_effect=AssertionError("No SSH allowed")):
            for remote in ("invalid", "a/b", "a@bad/host", "", "x@bad host"):
                with self.subTest(remote=remote), self.assertRaises(RuntimeError):
                    m.diagnose(remote)

    def test_mocked_ssh_forward_uses_only_local_temp_and_no_credentials(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0)
        with patch.object(m.subprocess, "run", side_effect=command):
            with patch.object(m.wire, "probe_one",
                              return_value="SMB3_02_NEGOTIATED") as probe:
                output = io.StringIO()
                with redirect_stdout(output):
                    m.diagnose("supervisor@ldap.thebergens.net")
        probe.assert_called_once_with("127.0.0.1", 1445)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "ssh")
        self.assertEqual(calls[1][0], "ssh")
        self.assertIn("127.0.0.1:1445:127.0.0.1:445", calls[0])
        self.assertIn("exit", calls[1])
        self.assertIn("SSH_FORWARD_SMB3_02_NEGOTIATED",
                      output.getvalue())
        self.assertIn("SSH_DIAGNOSTIC_LOCAL_LOG_DISCARDED",
                      output.getvalue())


if __name__ == "__main__":
    unittest.main()
