"""Offline tests for read-only directory preflight and explicit apply gating."""
import importlib.util
import io
import os
import stat
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/prepare_deletion_journal_directory.py"
spec = importlib.util.spec_from_file_location("prepare_deletion_directory", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def st(mode, uid, gid, dev=42, ino=10):
    return os.stat_result((mode, ino, dev, 1, uid, gid, 0, 0, 0, 0))


class JournalDirectoryPreparationTests(unittest.TestCase):
    def mock_inspect(self, child=None, parent=None, root=None):
        p = parent or st(stat.S_IFDIR | 0o750, 0, 988)
        r = root or st(stat.S_IFDIR | 0o755, 0, 0)
        self.enterContext(patch.object(mod.pwd, "getpwnam",
            return_value=type("User", (), {"pw_uid": 997, "pw_gid": 988})()))
        self.enterContext(patch.object(mod.os, "lstat", side_effect=lambda path:
            p if path == mod.PARENT else r))
        self.enterContext(patch.object(mod.os, "open", return_value=81))
        self.enterContext(patch.object(mod.os, "fstat", return_value=p))
        self.enterContext(patch.object(mod.os, "close"))
        if child is None:
            self.enterContext(patch.object(mod.os, "stat", side_effect=FileNotFoundError()))
        else:
            self.enterContext(patch.object(mod.os, "stat", return_value=child))

    def test_missing_child_plan_is_read_only(self):
        self.mock_inspect()
        with patch.object(mod.os, "mkdir") as mkdir, patch.object(mod.os, "chown") as chown:
            out = io.StringIO()
            with redirect_stdout(out):
                mod.main("plan")
            self.assertIn("READY_TO_CREATE", out.getvalue())
            self.assertIn("NO_FILES_CHANGED", out.getvalue())
            mkdir.assert_not_called()
            chown.assert_not_called()

    def test_existing_secure_child_plan(self):
        self.mock_inspect(child=st(stat.S_IFDIR | 0o700, 997, 988))
        out = io.StringIO()
        with redirect_stdout(out):
            mod.main("plan")
        self.assertIn("ALREADY_SECURE", out.getvalue())

    def test_symlink_child_rejected(self):
        self.mock_inspect(child=st(stat.S_IFLNK | 0o777, 997, 988))
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            mod.main("plan")

    def test_wrong_child_owner_rejected(self):
        self.mock_inspect(child=st(stat.S_IFDIR | 0o700, 0, 988))
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            mod.main("plan")

    def test_world_readable_child_rejected(self):
        self.mock_inspect(child=st(stat.S_IFDIR | 0o755, 997, 988))
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            mod.main("plan")

    def test_wrong_parent_mode_rejected(self):
        self.mock_inspect(parent=st(stat.S_IFDIR | 0o770, 0, 988))
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_PARENT"):
            mod.main("plan")

    def test_wrong_rootfs_rejected(self):
        self.mock_inspect(parent=st(stat.S_IFDIR | 0o750, 0, 988, dev=99))
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_PARENT"):
            mod.main("plan")

    def test_apply_requires_root(self):
        self.mock_inspect()
        with patch.object(mod.os, "geteuid", return_value=997), patch.object(mod.os, "mkdir") as mkdir:
            with self.assertRaisesRegex(RuntimeError, "ROOT_REQUIRED"):
                mod.main("apply")
            mkdir.assert_not_called()

    def test_apply_existing_directory_idempotent(self):
        self.mock_inspect(child=st(stat.S_IFDIR | 0o700, 997, 988))
        with patch.object(mod.os, "geteuid", return_value=0), patch.object(mod.os, "mkdir") as mkdir:
            out = io.StringIO()
            with redirect_stdout(out):
                mod.main("apply")
            self.assertIn("ALREADY_SECURE", out.getvalue())
            self.assertIn("NO_FILES_CHANGED", out.getvalue())
            mkdir.assert_not_called()

    def test_unknown_action_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_ACTION"):
            mod.main("write-journal")

    def test_apply_playbook_requires_explicit_approval(self):
        src = (ROOT / "ansible/playbooks/create-paperless-deletion-journal-directory.yml").read_text()
        self.assertIn("paperless_deletion_directory_apply_approved | default(false) | bool", src)
        self.assertIn("not ansible_check_mode", src)
        self.assertIn("argv: [pct, exec, '126', --, python3, '-', apply]", src)

    def test_plan_playbook_never_invokes_apply(self):
        src = (ROOT / "ansible/playbooks/plan-paperless-deletion-journal-directory.yml").read_text()
        self.assertIn("argv: [pct, exec, '126', --, python3, '-', plan]", src)
        self.assertNotIn("python3, '-', apply]", src)
        self.assertIn("changed_when: false", src)

    def test_no_journal_or_receipt_mutation_in_directory_script(self):
        src = SRC.read_text()
        self.assertNotIn("unlink(", src)
        self.assertNotIn("os.replace(", src)
        self.assertNotIn("write_decision(", src)
        self.assertNotIn("shutil.", src)
        self.assertIn('CHILD = "deletion-decisions"', src)


if __name__ == "__main__":
    unittest.main()
