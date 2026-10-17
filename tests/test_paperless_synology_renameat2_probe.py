"""Offline tests: disposable per-site Synology kernel rename probe safety."""
import contextlib
import importlib.util
import io
import os
import pwd
import stat
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


def simulate_initial_root_owned_fixture(fixture, mode=0o000):
    """Simulate DSM root-owned mkdtemp modes without root privileges.

    Patch only the FIRST lstat of the selected temporary fixture. Any
    subsequent lstat, including the post-chown verification, reads real
    filesystem metadata; production UID checks are never patched.
    """
    original_lstat = Path.lstat
    first = True

    def lstat(path):
        nonlocal first
        info = original_lstat(path)
        if path == fixture and first:
            first = False
            return SimpleNamespace(st_mode=(info.st_mode & ~0o7777) | mode,
                                   st_uid=0, st_dev=info.st_dev,
                                   st_ino=info.st_ino)
        return info

    return patch.object(Path, "lstat", lstat)


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

    def test_failed_initial_validation_cleans_only_empty_fixture(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            original = fixture.lstat()
            with contextlib.redirect_stdout(io.StringIO()):
                probe.cleanup_fixture(fixture, root, original, False, "homes")
            self.assertFalse(fixture.exists())

    def test_failed_initial_validation_never_recursively_deletes_unknown_entry(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            original = fixture.lstat()
            unknown = fixture / "do-not-delete.pdf"
            unknown.write_bytes(b"do not delete")
            with self.assertRaises(OSError):
                probe.cleanup_fixture(fixture, root, original, False, "homes")
            self.assertEqual(unknown.read_bytes(), b"do not delete")

    def test_cleanup_rejects_unexpected_file_after_fixture_invocation(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            original = fixture.lstat()
            (fixture / "unrelated.txt").write_bytes(b"preserve")
            with self.assertRaisesRegex(
                    RuntimeError, "FIXTURE_UNEXPECTED_CONTENT_REQUIRES_MANUAL_REVIEW"):
                probe.cleanup_fixture(fixture, root, original, True, "homes")
            self.assertTrue((fixture / "unrelated.txt").exists())

    def test_cleanup_known_fixture_removes_only_own_directory(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            original = fixture.lstat()
            (fixture / "scan-fixture").mkdir(mode=0o700)
            (fixture / "archive-fixture").mkdir(mode=0o700)
            (fixture / "archive-fixture/renamed.pdf").write_bytes(b"test")
            (fixture / "archive-fixture/collision.pdf").write_bytes(b"other")
            neighbor = root / "keep.txt"
            neighbor.write_bytes(b"remain")
            with contextlib.redirect_stdout(io.StringIO()):
                probe.cleanup_fixture(fixture, root, original, True, "homes")
            self.assertFalse(fixture.exists())
            self.assertEqual(neighbor.read_bytes(), b"remain")

    def test_cleanup_rejects_wrong_inode_or_outside_scope(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()
            incorrect = SimpleNamespace(st_mode=st.st_mode, st_dev=st.st_dev,
                                        st_ino=st.st_ino + 1)
            with self.assertRaisesRegex(
                    RuntimeError, "FIXTURE_CLEANUP_REQUIRES_MANUAL_REVIEW"):
                probe.cleanup_fixture(fixture, root, incorrect, False, "homes")
            other = root / "not-a-probe"
            other.mkdir(mode=0o700)
            with self.assertRaisesRegex(
                    RuntimeError, "FIXTURE_CLEANUP_REQUIRES_MANUAL_REVIEW"):
                probe.cleanup_fixture(other, root, other.lstat(), False, "homes")
            self.assertTrue(fixture.exists())
            self.assertTrue(other.exists())

    def test_actual_dsm_acl_header_with_spaces_before_newlines(self):
        # Exact live paperless-scan diagnostic (15.10.2026).
        stdout = (
            "ACL version: 1 \n"
            "Archive: is_inherit,is_support_ACL \n"
            "Owner: [root(user)] \n"
            "--------------------- \n"
            "\t [0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:1)\n"
        )
        result = subprocess.CompletedProcess(
            [], 0, stdout=stdout, stderr="")
        self.assertTrue(probe._has_expected_inherited_dsm_acl(result))

    def test_unpadded_dsm_acl_header_also_accepted(self):
        result = subprocess.CompletedProcess(
            [], 0, stdout=(
                "ACL version: 1\n"
                "Archive: is_inherit,is_support_ACL\n"),
            stderr="")
        self.assertTrue(probe._has_expected_inherited_dsm_acl(result))

    def test_dsm_acl_header_does_not_accept_changed_flags_or_order(self):
        headers = (
            "ACL version: 1 \nArchive: has_ACL \n",
            "Archive: is_inherit,is_support_ACL \nACL version: 1 \n",
            "ACL version: 2 \nArchive: is_inherit,is_support_ACL \n",
            "ACL version: 1 \nArchive: is_inherit,is_support_ACL,has_ACL \n",
            "ACL version: 1 \nOwner: [root(user)]\n"
            "Archive: is_inherit,is_support_ACL \n",
        )
        for output in headers:
            with self.subTest(stdout=output):
                result = subprocess.CompletedProcess(
                    [], 0, stdout=output, stderr="")
                self.assertFalse(probe._has_expected_inherited_dsm_acl(result))

    def test_dsm_acl_header_rejects_leading_or_embedded_whitespace(self):
        headers = (
            " ACL version: 1 \nArchive: is_inherit,is_support_ACL \n",
            "ACL version: 1 \n Archive: is_inherit,is_support_ACL \n",
            "ACL version: 1 invalid\nArchive: is_inherit,is_support_ACL \n",
            "ACL version: 1 \nArchive: is_inherit, is_support_ACL \n",
        )
        for output in headers:
            with self.subTest(stdout=output):
                result = subprocess.CompletedProcess(
                    [], 0, stdout=output, stderr="")
                self.assertFalse(probe._has_expected_inherited_dsm_acl(result))

    def test_dsm_acl_header_rejects_error_status_or_stderr(self):
        good = "ACL version: 1 \nArchive: is_inherit,is_support_ACL \n"
        for rc, stderr in ((1, ""), (255, ""), (0, "warning")):
            with self.subTest(rc=rc, stderr=stderr):
                result = subprocess.CompletedProcess(
                    [], rc, stdout=good, stderr=stderr)
                self.assertFalse(probe._has_expected_inherited_dsm_acl(result))

    def test_homes_0711_is_allowed_only_at_verified_exact_dsm_root(self):
        parent = SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o711)
        self.assertTrue(probe._allowed_initial_fixture_mode(
            Path("/volume1/homes"), parent, 0o711))
        for name in ("/volume1/paperless-scan",
                     "/volume1/homes/subfolder",
                     "/volume1/homes-fake"):
            with self.subTest(path=name):
                self.assertFalse(probe._allowed_initial_fixture_mode(
                    Path(name), parent, 0o711))

    def test_homes_0711_is_refused_if_root_identity_mode_or_type_differs(self):
        for parent in (
            SimpleNamespace(st_uid=1000, st_mode=stat.S_IFDIR | 0o711),
            SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o700),
            SimpleNamespace(st_uid=0, st_mode=stat.S_IFLNK | 0o711),
        ):
            with self.subTest(parent=parent):
                self.assertFalse(probe._allowed_initial_fixture_mode(
                    Path("/volume1/homes"), parent, 0o711))

    def test_unexpected_modes_always_fail_even_under_homes(self):
        parent = SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o711)
        for mode in (0o001, 0o071, 0o644, 0o755, 0o777, 0o7111):
            with self.subTest(mode=oct(mode)):
                self.assertFalse(probe._allowed_initial_fixture_mode(
                    Path("/volume1/homes"), parent, mode))
        self.assertTrue(probe._allowed_initial_fixture_mode(
            Path("/volume1/paperless-scan"), parent, 0o000))
        self.assertTrue(probe._allowed_initial_fixture_mode(
            Path("/volume1/paperless-scan"), parent, 0o700))

    def test_homes_0711_requires_inherited_native_acl_before_chown(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()

            def expected_homes_mode(site, parent, mode):
                self.assertEqual(site, root)
                self.assertEqual(mode, 0o711)
                return True

            with simulate_initial_root_owned_fixture(
                    fixture, mode=0o711), \
                 patch.object(probe, "_allowed_initial_fixture_mode",
                              side_effect=expected_homes_mode), \
                 patch.object(probe, "_synology_acl_tool",
                              return_value="/fake/synoacltool"), \
                 patch.object(probe, "_linux_acl_only", return_value=True), \
                 patch.object(probe.subprocess, "run") as calls:
                with self.assertRaisesRegex(
                        RuntimeError, "HOMES_INHERITED_ACL_REQUIRED"):
                    probe.secure_new_fixture(
                        fixture, root, st,
                        SimpleNamespace(pw_uid=os.geteuid(),
                                        pw_gid=os.getegid()),
                        st.st_dev, "/fake/btrfs", "437")
                calls.assert_not_called()
            self.assertTrue(fixture.exists())

    def test_inherited_dsm_acl_is_removed_only_from_new_fixture(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()
            events = []
            response = [
                subprocess.CompletedProcess([], 0,
                    stdout="ACL version: 1 \nArchive: is_inherit,is_support_ACL \n", stderr=""),
                subprocess.CompletedProcess([], 0,
                    stdout="ACL version: 1 \nArchive: is_inherit,is_support_ACL \n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                subprocess.CompletedProcess([], 255,
                    stdout="(synoacltool.c, 596)It's Linux mode\n", stderr=""),
            ]

            def run(argv, **_):
                events.append(argv)
                return response.pop(0)

            service = SimpleNamespace(pw_uid=os.geteuid(),
                                      pw_gid=os.getegid())
            with simulate_initial_root_owned_fixture(fixture), \
                 patch.object(probe, "_synology_acl_tool",
                              return_value="/fake/synoacltool"), \
                 patch.object(probe.subprocess, "run", side_effect=run), \
                 patch.object(probe.os, "chown", return_value=None), \
                 patch.object(probe, "subvol_id", return_value="7446"):
                probe.secure_new_fixture(fixture, root, st, service,
                                         st.st_dev, "/fake/btrfs", "7446")
            self.assertEqual(
                events[2], ["/fake/synoacltool", "-del", str(fixture)])
            self.assertEqual(stat.S_IMODE(fixture.stat().st_mode), 0o700)
            self.assertEqual(response, [])

    def test_unexpected_dsm_acl_never_removed(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()
            commands = []

            def run(argv, **_):
                commands.append(argv)
                return subprocess.CompletedProcess(
                    [], 0, stdout="ACL version: 1\nArchive: has_ACL\n",
                    stderr="")

            with simulate_initial_root_owned_fixture(fixture), \
                 patch.object(probe, "_synology_acl_tool",
                              return_value="/fake/synoacltool"), \
                 patch.object(probe.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(
                        RuntimeError, "UNEXPECTED_INHERITED_FIXTURE_ACL"):
                    probe.secure_new_fixture(
                        fixture, root, st,
                        SimpleNamespace(pw_uid=os.geteuid(),
                                        pw_gid=os.getegid()),
                        st.st_dev, "/fake/btrfs", "7446")
            self.assertFalse(any("-del" in args for args in commands))
            self.assertTrue(fixture.exists())

    def test_acl_removal_failure_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()
            responses = [
                subprocess.CompletedProcess([], 0,
                    stdout="ACL version: 1\nArchive: is_inherit,is_support_ACL\n", stderr=""),
                subprocess.CompletedProcess([], 0,
                    stdout="ACL version: 1\nArchive: is_inherit,is_support_ACL\n", stderr=""),
                subprocess.CompletedProcess([], 1,
                    stdout="", stderr="denied"),
            ]
            with simulate_initial_root_owned_fixture(fixture), \
                 patch.object(probe, "_synology_acl_tool",
                              return_value="/fake/synoacltool"), \
                 patch.object(probe.subprocess, "run",
                              side_effect=responses):
                with self.assertRaisesRegex(
                        RuntimeError, "FIXTURE_ACL_REMOVAL_FAILED"):
                    probe.secure_new_fixture(
                        fixture, root, st,
                        SimpleNamespace(pw_uid=os.geteuid(),
                                        pw_gid=os.getegid()),
                        st.st_dev, "/fake/btrfs", "7446")

    def test_fixture_with_bad_inode_never_gets_acl_mutation(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()
            fake = SimpleNamespace(st_ino=st.st_ino + 1)
            with simulate_initial_root_owned_fixture(fixture), \
                 patch.object(probe, "_synology_acl_tool") as acl:
                with self.assertRaisesRegex(RuntimeError, "UNSAFE_NEW_FIXTURE"):
                    probe.secure_new_fixture(
                        fixture, root, fake,
                        SimpleNamespace(pw_uid=os.geteuid(),
                                        pw_gid=os.getegid()),
                        st.st_dev, "/fake/btrfs", "7446")
                acl.assert_not_called()

    def test_nonempty_initial_fixture_never_gets_acl_mutation(self):
        with tempfile.TemporaryDirectory(prefix="rename-safety-") as tmp:
            root = Path(tmp)
            fixture = root / ".bergen-rename-probe-owned"
            fixture.mkdir(mode=0o700)
            st = fixture.lstat()
            (fixture / "unexpected.pdf").write_bytes(b"preserve")
            with simulate_initial_root_owned_fixture(fixture), \
                 patch.object(probe, "_synology_acl_tool") as acl:
                with self.assertRaisesRegex(RuntimeError, "NONEMPTY_NEW_FIXTURE"):
                    probe.secure_new_fixture(
                        fixture, root, st,
                        SimpleNamespace(pw_uid=os.geteuid(),
                                        pw_gid=os.getegid()),
                        st.st_dev, "/fake/btrfs", "7446")
                acl.assert_not_called()
            self.assertEqual(
                (fixture / "unexpected.pdf").read_bytes(), b"preserve")

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
