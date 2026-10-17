"""Fail-closed tests for independent Synology protected archive site setup."""
import importlib.util
import os
import tempfile
import stat
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

MODULE = (Path(__file__).resolve().parents[1] /
          "ansible/files/paperless/prepare_synology_protected_archive_site.py")
spec = importlib.util.spec_from_file_location("protected_site_prepare", MODULE)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


def line(role, name, perm, effect="allow"):
    if role in ("owner", "everyone"):
        return (f"? [1] {role}::{effect}:{perm}:fd-- (level:0)\n")
    return f"? [1] {role}:{name}:{effect}:{perm}:fd-- (level:0)\n"


class ProtectedSitePreparationTests(unittest.TestCase):
    def test_two_site_scope_isolation(self):
        self.assertEqual(stage.SITE_SCOPES["homes"],
                         frozenset(("Privat/thomas", "Privat/nadja")))
        self.assertEqual(stage.SITE_SCOPES["paperless-scan"],
                         frozenset(("Eltern", "Familie")))

    def test_real_homes_owner_and_everyone_traverse_only(self):
        output = (line("owner", "", "rwxpdDaARWcCo")
                  + line("everyone", "", "--x----------"))
        stage.parse_parent_access(output)

    def test_nonadmin_parent_delete_child_denied(self):
        for role, user in (("everyone", ""),
                           ("group", "Familie@bergen.intern"),
                           ("group", "Eltern@bergen.intern"),
                           ("user", "thomas@bergen.intern")):
            with self.subTest(role=role, user=user):
                with self.assertRaisesRegex(
                        RuntimeError, "NONADMIN_PARENT_DELETE_GRANT"):
                    stage.parse_parent_access(
                        line(role, user, "rwxpdDaARWc--"))

    def test_nonadmin_parent_write_execute_denied(self):
        with self.assertRaisesRegex(RuntimeError, "NONADMIN_PARENT_DELETE_GRANT"):
            stage.parse_parent_access(
                line("everyone", "", "rwx---a-R-c--"))

    def test_root_and_service_parent_grants_permitted(self):
        stage.parse_parent_access(
            line("owner", "", "rwxpdDaARWcCo")
            + line("group", "administrators", "rwxpdDaARWc--")
            + line("group", "administrators@bergen.intern", "rwxpdDaARWc--")
            + line("user", "paperless-sync", "rwxpdDaARWc--"))

    def test_unrecognized_special_principal_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "UNRECOGNIZED_NATIVE_ACE"):
            stage.parse_parent_access(
                "? [3] anonymous::allow:rwxpdDaARWcCo:fd-- (level:0)\n")

    def test_malformed_ace_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "UNRECOGNIZED_NATIVE_ACE"):
            stage.parse_parent_access(
                "? [3] everyone::allow:rwxpdDaARWcCo:BAD (level:0)\n")

    def test_missing_ace_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "MISSING_PARENT_ACL"):
            stage.parse_parent_access("ACL version: 1\n")

    def test_readonly_verify_complete_empty_homes_tree(self):
        reply = subprocess.CompletedProcess(
            ["synoacltool"], 255,
            stdout="(synoacltool.c, 596)It's Linux mode\n",
            stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".bergen-paperless-archive"
            for path in (root, root / "Privat", root / "Privat/thomas",
                         root / "Privat/nadja"):
                path.mkdir(mode=0o700)
            with patch.object(stage.subprocess, "run", return_value=reply):
                self.assertEqual(stage.verify_empty_site_tree(
                    root, stage.SITE_SCOPES["homes"],
                    os.geteuid(), root.stat().st_dev, "acl"), 4)

    def test_readonly_verify_rejects_unexpected_pdf_without_deleting_it(self):
        reply = subprocess.CompletedProcess(
            ["synoacltool"], 255,
            stdout="(synoacltool.c, 596)It's Linux mode\n",
            stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".bergen-paperless-archive"
            for path in (root, root / "Eltern", root / "Familie"):
                path.mkdir(mode=0o700)
            unexpected = root / "Eltern/test.pdf"
            unexpected.write_bytes(b"fixture")
            with patch.object(stage.subprocess, "run", return_value=reply):
                with self.assertRaisesRegex(
                        RuntimeError, "ARCHIVE_TREE_NOT_EMPTY_OR_UNEXPECTED_ENTRY"):
                    stage.verify_empty_site_tree(
                        root, stage.SITE_SCOPES["paperless-scan"],
                        os.geteuid(), root.stat().st_dev, "acl")
            self.assertEqual(unexpected.read_bytes(), b"fixture")

    def test_readonly_verify_rejects_extra_symlink_even_if_private(self):
        reply = subprocess.CompletedProcess(
            ["synoacltool"], 255,
            stdout="(synoacltool.c, 596)It's Linux mode\n",
            stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".bergen-paperless-archive"
            for path in (root, root / "Eltern", root / "Familie"):
                path.mkdir(mode=0o700)
            (root / "unexpected").symlink_to("/tmp")
            with patch.object(stage.subprocess, "run", return_value=reply):
                with self.assertRaisesRegex(
                        RuntimeError, "ARCHIVE_TREE_NOT_EMPTY_OR_UNEXPECTED_ENTRY"):
                    stage.verify_empty_site_tree(
                        root, stage.SITE_SCOPES["paperless-scan"],
                        os.geteuid(), root.stat().st_dev, "acl")

    def test_device_root_requires_device_boundary(self):
        source = Path("/volume1/homes/thomas/Paperless")
        status = {
            source: SimpleNamespace(st_dev=47),
            Path("/volume1/homes/thomas"): SimpleNamespace(st_dev=47),
            Path("/volume1/homes"): SimpleNamespace(st_dev=47),
            Path("/volume1"): SimpleNamespace(st_dev=104),
        }
        with patch.object(stage, "inspect_dir", side_effect=lambda p: status[p]):
            self.assertEqual(stage.device_root(source), Path("/volume1/homes"))

    def test_stage_empty_has_no_rename_or_delete_operations(self):
        source = MODULE.read_text()
        for token in ("os.unlink(", ".unlink(", "os.replace(", "os.rename(",
                      "shutil.move(", "os.rmdir(", ".rmdir(", "shutil.rmtree(",
                      "archive-move.enabled", "--commit"):
            if token == "archive-move.enabled":
                self.assertIn(token, source)  # only absent gate check
            else:
                self.assertNotIn(token, source)

    def test_linux_mode_only_accepted_with_owner_mode_and_device(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=123,
                               st_dev=47, st_nlink=1)
        reply = subprocess.CompletedProcess(
            ["synoacltool"], 255, stdout="(synoacltool.c, 596)It's Linux mode\n",
            stderr="")
        with patch.object(stage, "inspect_dir", return_value=info), \
             patch.object(stage.subprocess, "run", return_value=reply):
            stage.validate_private_directory(Path("/tmp/test"), 123, 47, "acl")

    def test_native_dsm_acl_on_archive_is_not_accepted_without_review(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=123,
                               st_dev=47, st_nlink=1)
        reply = subprocess.CompletedProcess(
            ["synoacltool"], 0, stdout="ACL version: 1", stderr="")
        with patch.object(stage, "inspect_dir", return_value=info), \
             patch.object(stage.subprocess, "run", return_value=reply):
            with self.assertRaisesRegex(
                    RuntimeError, "PRIVATE_ARCHIVE_NATIVE_ACL_REVIEW_REQUIRED"):
                stage.validate_private_directory(Path("/tmp/test"), 123, 47, "acl")


if __name__ == "__main__":
    unittest.main()
