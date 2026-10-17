"""Offline tests of read-only live journal target planning."""
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless/plan_deleted_by_user_journal_target.py"
JOURNAL = ROOT / "ansible/files/paperless/deleted_by_user_decision_journal.py"
spec = importlib.util.spec_from_file_location("user_deletion_plan", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
spec2 = importlib.util.spec_from_file_location("user_deletion_schema", JOURNAL)
schema = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(schema)

DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"


def record():
    receiver = "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf"
    nas = dict(schema_version=1, sender_receipt=schema.SENDER,
               scope=schema.SCOPE, source=schema.SOURCE,
               receiver_source=receiver, sha256=DIGEST,
               sender_status="SENT", nas_original_absent=True)
    deleted = dict(schema_version=1, bridge_receipt=schema.BRIDGE,
                   document_id=26, receiver_source=receiver, sha256=DIGEST,
                   proposed_status="DELETED_IN_PAPERLESS",
                   live_document_absent=True, original_filename_absent=True)
    return schema.build(nas, deleted)


class JournalTargetPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.path.chmod(0o700)
        self.uid = os.geteuid()
        self.gid = os.getegid()
        self.enterContext(patch.object(mod, "EXPECTED_UID", self.uid))
        self.enterContext(patch.object(mod, "EXPECTED_GID", self.gid))
        self.enterContext(patch.object(mod.pwd, "getpwnam", return_value=
                                SimpleNamespace(pw_uid=self.uid, pw_gid=self.gid)))
        real_lstat = os.lstat
        root_dev = real_lstat("/").st_dev
        fake_parent = SimpleNamespace(st_mode=stat.S_IFDIR | 0o750,
                                      st_uid=0, st_gid=self.gid, st_dev=root_dev)
        self.enterContext(patch.object(mod.os, "lstat",
            side_effect=lambda path: fake_parent if path == self.path.parent
            else real_lstat(path)))
        self.rec = record()

    def run_plan(self):
        output = io.StringIO()
        with redirect_stdout(output):
            mod.plan(self.rec, directory=self.path)
        return output.getvalue()

    def test_event_id_is_expected(self):
        self.assertEqual(self.rec["event_id"], mod.EXPECTED_EVENT)

    def test_new_target_read_only(self):
        with patch.object(mod.os, "mkdir") as mkdir, patch.object(mod.os, "unlink") as unlink:
            out = self.run_plan()
        self.assertIn("READY_TO_PUBLISH", out)
        self.assertIn("NO_JOURNAL_WRITTEN", out)
        self.assertIn("NO_FILES_CHANGED", out)
        self.assertEqual(list(self.path.iterdir()), [])
        mkdir.assert_not_called()
        unlink.assert_not_called()

    def test_existing_identical(self):
        target = self.path / (mod.EXPECTED_EVENT + ".json")
        target.write_bytes(schema.canonical(self.rec))
        target.chmod(0o600)
        self.assertIn("ALREADY_IDENTICAL", self.run_plan())

    def test_existing_conflicting_bytes(self):
        target = self.path / (mod.EXPECTED_EVENT + ".json")
        target.write_bytes(schema.canonical(self.rec).replace(b"DELETED_BY_USER", b"DELETED_BY_XXXX"))
        target.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "CONFLICTING_JOURNAL_PAYLOAD"):
            self.run_plan()

    def test_existing_symlink_rejected(self):
        (self.path / (mod.EXPECTED_EVENT + ".json")).symlink_to(self.path / "missing")
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            self.run_plan()

    def test_existing_world_readable_rejected(self):
        target = self.path / (mod.EXPECTED_EVENT + ".json")
        target.write_bytes(schema.canonical(self.rec))
        target.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            self.run_plan()

    def test_directory_world_readable_rejected(self):
        self.path.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
            self.run_plan()

    def test_directory_symlink_rejected(self):
        alias = self.path.parent / (self.path.name + "-alias")
        alias.symlink_to(self.path, target_is_directory=True)
        self.addCleanup(alias.unlink)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
            mod.plan(self.rec, directory=alias)

    def test_wrong_event_rejected(self):
        self.rec["event_id"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_USER_DELETION_TARGET"):
            self.run_plan()

    def test_wrong_document_rejected(self):
        self.rec["document_id"] = 27
        with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_USER_DELETION_TARGET"):
            self.run_plan()

    def test_no_write_primitives(self):
        source = SOURCE.read_text()
        self.assertNotIn("os.mkdir(", source)
        self.assertNotIn("os.unlink(", source)
        self.assertNotIn("os.link(", source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn("open(", source.split("def plan(", 1)[1].split('if __name__', 1)[0].replace("os.open(", ""))

    def test_live_playbook_rechecks_both_sources(self):
        play = (ROOT / "ansible/playbooks/plan-paperless-deleted-by-user-journal.yml").read_text()
        self.assertIn("export_deleted_import_candidate.py", play)
        self.assertIn("export_deleted_by_user_nas_evidence.py", play)
        self.assertIn("preview_deleted_by_user_policy.py", play)
        self.assertIn("deleted_by_user_decision_journal.py", play)
        self.assertIn("plan_deleted_by_user_journal_target.py", play)
        self.assertIn("runuser", play)
        self.assertIn("paperless-ingest", play)
        self.assertNotIn("publish_once(", play)
        self.assertNotIn("journal_apply_approved", play)

    def test_no_files_changed_markers(self):
        play = (ROOT / "ansible/playbooks/plan-paperless-deleted-by-user-journal.yml").read_text()
        self.assertIn("changed_when: false", play)
        self.assertIn("NO_JOURNAL_WRITTEN", play)
        self.assertIn("NO_RECEIPTS_CHANGED", play)
        self.assertIn("NO_FILES_CHANGED", play)


if __name__ == "__main__":
    unittest.main()
