"""Synthetic read-only checks for NAS SMB share path preflight."""
import ast
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

BASE = Path(__file__).resolve().parents[1] / "ansible"
SCRIPT = BASE / "files/paperless/audit_synology_smb_share_mapping.py"
PLAYBOOK = BASE / "playbooks/audit-paperless-synology-smb-share-mapping.yml"

spec = importlib.util.spec_from_file_location("smb_map", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SMBShareMapTests(unittest.TestCase):
    def output(self, share, path):
        return ("SYNOSHARE data dump:\n"
                "Name .......[" + share + "]\n"
                "Comment ....[]\n"
                "Path .......[" + path + "]\n"
                "RW list ....[admin]\n")

    def test_both_exact_synology_site_root_mappings_accepted(self):
        for share, expected in m.SHARES.items():
            with self.subTest(share=share):
                self.assertEqual(
                    m.parse_share_path(self.output(share, expected), share),
                    expected)

    def test_wrong_path_and_nesting_fail_closed(self):
        for share in m.SHARES:
            correct = m.SHARES[share]
            bads = ("/volume1/elsewhere", correct + "/subfolder",
                    "/volume1", correct + "/../" + share,
                    "/" + share, "")
            for bad in bads:
                with self.subTest(share=share, bad=bad):
                    with self.assertRaises(RuntimeError):
                        m.parse_share_path(self.output(share, bad), share)

    def test_duplicate_missing_or_malformed_path_rejected(self):
        for share, root in m.SHARES.items():
            valid = self.output(share, root)
            candidates = (
                valid + "Path .......[" + root + "]\n",
                "SYNOSHARE data dump\nName .....[" + share + "]\n",
                valid.replace("Path .......[", "Path ["),
                valid.replace("Path .......[", "Path ...<"),
            )
            for output in candidates:
                with self.subTest(share=share, output=output[:40]):
                    with self.assertRaises(RuntimeError):
                        m.parse_share_path(output, share)

    def test_native_share_lookup_is_read_only(self):
        code = SCRIPT.read_text()
        for banned in ("--del", "--add", "--rename", "--setuser", "--setvol",
                       "os.unlink(", "os.rename(", "os.replace(", "os.chmod(",
                       "os.mkdir(", ".write_text(", "shutil.move("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, code)
        self.assertIn('"--get"', code)
        self.assertIn("NO_FILES_CHANGED", code)

    def test_unexpected_cli_status_never_proves_mapping(self):
        state = SimpleNamespace(returncode=255, stdout="", stderr="secret")
        with patch.object(m.subprocess, "run", return_value=state):
            with patch.object(Path, "lstat", return_value=SimpleNamespace(
                    st_mode=0o40700, st_uid=0)):
                with self.assertRaisesRegex(
                        RuntimeError, "SYNO_SHARE_LOOKUP_FAILED"):
                    m.check_share(Path("/usr/syno/sbin/synoshare"), "homes")

    def test_playbook_yaml_and_required_release_markers(self):
        import yaml
        plays = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(plays), 1)
        tasks = plays[0]["tasks"]
        self.assertEqual(len(tasks), 6)
        self.assertFalse(tasks[1]["changed_when"])
        self.assertFalse(tasks[4]["changed_when"])
        must = tasks[2]["ansible.builtin.assert"]["that"]
        self.assertTrue(any("NAS_SMB_SHARE_MAPPING_VERIFIED 2" in x
                            for x in must))
        self.assertIn("SMB_NEGATIVE_RIGHTS_NOT_TESTED",
                      PLAYBOOK.read_text())
        ast.parse(SCRIPT.read_text(), filename=str(SCRIPT))


if __name__ == "__main__":
    unittest.main()
