"""Offline tests: disposable per-site Synology kernel rename probe safety."""
import contextlib
import importlib.util
import io
import os
import pwd
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ansible/files/paperless/probe_synology_archive_renameat2.py"
BIN = ROOT / "ansible/files/paperless"
spec = importlib.util.spec_from_file_location("synology_rename_fixture", MODULE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class IsolatedSynologyRenameTests(unittest.TestCase):
    def test_exact_scope_to_site_mapping(self):
        self.assertEqual(probe.SITES["homes"],
                         ("Privat/thomas", "Privat/nadja"))
        self.assertEqual(probe.SITES["paperless-scan"],
                         ("Eltern", "Familie"))

    def test_legacy_and_site_gates_checked(self):
        self.assertEqual(set(probe.GATES), {
            "archive-move.enabled", "archive-move.homes.enabled",
            "archive-move.paperless-scan.enabled"})

    def test_btrfs_subvolume_id_rejects_non_numeric_result(self):
        for output in ("", "unexpected", "0", "437 7446", "437\nother"):
            with self.subTest(output=output), \
                 patch.object(probe.subprocess, "run",
                              return_value=subprocess.CompletedProcess(
                                  [], 0, stdout=output, stderr="")):
                with self.assertRaisesRegex(
                        RuntimeError, "UNVERIFIED_BTRFS_SUBVOLUME_ID"):
                    probe.subvol_id("/sbin/btrfs", Path("/tmp/scope"))

    def test_btrfs_rootid_requires_successful_command(self):
        with patch.object(probe.subprocess, "run",
                          return_value=subprocess.CompletedProcess(
                              [], 2, stdout="437\n", stderr="denied")):
            with self.assertRaisesRegex(
                    RuntimeError, "UNVERIFIED_BTRFS_SUBVOLUME_ID"):
                probe.subvol_id("/sbin/btrfs", Path("/tmp/scope"))

    def test_btrfs_rootid_accepts_known_numeric_id(self):
        with patch.object(probe.subprocess, "run",
                          return_value=subprocess.CompletedProcess(
                              [], 0, stdout="437\n", stderr="")):
            self.assertEqual(
                probe.subvol_id("/sbin/btrfs", Path("/tmp/scope")), "437")

    def test_unprivileged_fixture_uses_real_noreplace_and_preserves_inode(self):
        # Only this test's temporary tree is touched. Use the executing test
        # UID instead of an actual Synology paperless-sync account.
        with tempfile.TemporaryDirectory(prefix="bergen-fixture-offline-") as tmp:
            root = Path(tmp) / "isolated"
            root.mkdir(mode=0o700)
            fake_user = SimpleNamespace(pw_uid=os.geteuid())
            output = io.StringIO()
            with patch.object(pwd, "getpwnam", return_value=fake_user), \
                 patch.object(sys, "argv", [
                     "fixture", str(root), "paperless-scan", str(BIN)]), \
                 contextlib.redirect_stdout(output):
                exec(probe.UNPRIVILEGED_FIXTURE, {"__name__": "__main__"})
            result = output.getvalue()
            self.assertIn(
                "SYNODB_RENAME_COLLISION_PROTECTED paperless-scan", result)
            self.assertIn(
                "SYNODB_RENAME_NOREPLACE_OK paperless-scan", result)
            self.assertFalse((root / "scan-fixture/test.pdf").exists())
            self.assertTrue((root / "archive-fixture/renamed.pdf").is_file())
            self.assertEqual(
                (root / "archive-fixture/collision.pdf").read_bytes(),
                b"existing target must remain unmodified")

    def test_unprivileged_fixture_rejects_wrong_execution_identity(self):
        with tempfile.TemporaryDirectory(prefix="bergen-fixture-offline-") as tmp:
            root = Path(tmp) / "isolated"
            root.mkdir(mode=0o700)
            wrong_uid = os.geteuid() + 5000
            with patch.object(pwd, "getpwnam",
                              return_value=SimpleNamespace(pw_uid=wrong_uid)), \
                 patch.object(sys, "argv", [
                     "fixture", str(root), "homes", str(BIN)]):
                with self.assertRaisesRegex(
                        AssertionError, "INCORRECT_UNPRIVILEGED_IDENTITY"):
                    exec(probe.UNPRIVILEGED_FIXTURE, {"__name__": "__main__"})
            self.assertEqual(list(root.iterdir()), [])

    def test_no_live_archive_path_is_used_as_fixture_target(self):
        text = MODULE.read_text()
        self.assertIn('prefix=".bergen-rename-probe-"', text)
        self.assertIn('dir=root', text)
        self.assertIn("shutil.rmtree(fixture)", text)
        self.assertNotIn("shutil.rmtree(archive)", text)
        self.assertNotIn("shutil.rmtree(source)", text)
        self.assertNotIn(".paperless-archive", text)


if __name__ == "__main__":
    unittest.main()
