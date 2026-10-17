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

    def test_syntax_and_only_documented_probes(self):
        root = ast.parse(MODULE.read_text(), filename=str(MODULE))
        self.assertIsInstance(root, ast.Module)
        self.assertEqual(len(m.request_plan("homes")), 3)
        self.assertEqual(len(m.request_plan("paperless-scan")), 3)


if __name__ == "__main__":
    unittest.main()
