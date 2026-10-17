"""Offline regression checks for the separately gated production journal publisher.

These tests never invoke the production apply playbook.
"""
import importlib.util
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/publish_deleted_by_user_journal.py"
PLAY = ROOT / "ansible/playbooks/publish-paperless-deleted-by-user-journal.yml"
spec = importlib.util.spec_from_file_location("paperless_user_deletion_publish", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class JournalPublicationGateTests(unittest.TestCase):
    def test_publisher_requires_exact_payload_shape(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_JOURNAL_PUBLICATION_REQUEST"):
            mod.main({})

    def test_publisher_requires_restricted_identity(self):
        request = {k: "" for k in ("nas", "deleted", "schema_source",
                                   "store_source", "plan_source")}
        with patch.object(mod.pwd, "getpwnam", return_value=SimpleNamespace(
                pw_uid=997, pw_gid=988)), patch.object(mod.os, "geteuid",
                return_value=0), patch.object(mod, "_load_module") as load:
            with self.assertRaisesRegex(RuntimeError, "RESTRICTED_INGEST_IDENTITY_REQUIRED"):
                mod.main(request)
            load.assert_not_called()

    def test_unexpected_module_source_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_REVIEWED_SOURCE"):
            mod._load_module("fake", "print('bad')")

    def test_exact_fixed_event_and_payload_sha(self):
        self.assertEqual(mod.EXPECTED_EVENT,
            "f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26")
        self.assertEqual(mod.EXPECTED_RECORD_SHA,
            "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a")

    def test_apply_playbook_has_separate_gate_before_mutation(self):
        play = PLAY.read_text()
        gate = play.index("paperless_user_deletion_journal_apply_approved | default(false) | bool")
        writer = play.index("publish_deleted_by_user_journal.py")
        self.assertLess(gate, writer)
        self.assertIn("not ansible_check_mode", play)
        self.assertIn("USER_DELETION_JOURNAL_WRITE_NOT_APPROVED", play)
        self.assertNotIn("paperless_deletion_directory_apply_approved", play)

    def test_apply_rechecks_both_live_absences(self):
        play = PLAY.read_text()
        first_write = play.index("name: Publish exactly one immutable-named journal record")
        before = play[:first_write]
        self.assertGreaterEqual(before.count("export_deleted_import_candidate.py"), 2)
        self.assertGreaterEqual(before.count("export_deleted_by_user_nas_evidence.py"), 2)
        self.assertGreaterEqual(before.count("preview_deleted_by_user_policy.py"), 2)
        self.assertIn("deleted_nas_final_proof.stdout == deleted_nas_proof.stdout", before)
        self.assertIn("deleted_paperless_final_proof.stdout == deleted_paperless_proof.stdout", before)

    def test_apply_uses_restricted_ingest_user(self):
        play = PLAY.read_text()
        self.assertIn("runuser", play)
        self.assertIn("paperless-ingest", play)
        self.assertIn("deleted_by_user_decision_store.py", play)
        self.assertIn("deleted_by_user_decision_journal.py", play)
        self.assertIn("plan_deleted_by_user_journal_target.py", play)

    def test_publication_never_changes_receipts_or_documents(self):
        src = SRC.read_text()
        self.assertNotIn("os.unlink(", src)
        self.assertNotIn("os.replace(", src)
        self.assertNotIn("subprocess.", src)
        self.assertNotIn("requests.", src)
        self.assertIn("store.publish_once(", src)
        self.assertIn("store._existing_matches(", src)
        self.assertIn("NO_RECEIPTS_CHANGED", src)
        self.assertIn("NO_REIMPORT_OR_RESTORE", src)
        self.assertIn("NO_ARCHIVE_AUTHORIZATION", src)

    def test_existing_plan_remains_read_only(self):
        plan = (ROOT / "ansible/playbooks/plan-paperless-deleted-by-user-journal.yml").read_text()
        self.assertNotIn("publish_deleted_by_user_journal.py", plan)
        self.assertNotIn("paperless_user_deletion_journal_apply_approved", plan)

    def test_writer_has_no_default_autorun_without_apply(self):
        src = SRC.read_text()
        self.assertIn('sys.argv != [sys.argv[0], "--apply"]', src)
        self.assertIn("EXPLICIT_APPLY_ARGUMENT_REQUIRED", src)


if __name__ == "__main__":
    unittest.main()
