"""Offline-only regression tests for the second unverified Paperless import."""
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/diagnose_paperless_import_7a92.py"
PLAY = ROOT / "ansible/playbooks/diagnose-paperless-import-7a92.yml"
spec = importlib.util.spec_from_file_location("diagnose_7a92", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class DiagnoseSecondImportTests(unittest.TestCase):
    def test_pinned_receipt(self):
        self.assertEqual(mod.RECEIPT_ID, "7a92b91deb7b2e8e35f9f710.json")

    def test_script_is_read_only(self):
        src = SRC.read_text()
        for forbidden in ("os.unlink(", "os.replace(", "os.mkdir(", "os.chmod(",
                          "os.chown(", ".write_text(", ".write_bytes(", "publish_once(",
                          "receipt['status'] =", 'receipt["status"] ='):
            self.assertNotIn(forbidden, src)

    def test_inspection_queries_by_document_id_not_only_filename(self):
        src = SRC.read_text()
        self.assertIn("Document.objects.filter(pk=pk)", src)
        self.assertIn("expected_filename_exists", src)
        self.assertIn("checksum_matches_receipt", src)
        self.assertIn("owner_matches_receipt", src)
        self.assertIn("root_document_id", src)

    def test_inspect_accepts_absent_document(self):
        proc = SimpleNamespace(
            returncode=0,
            stdout='BP_IMPORT_DIAGNOSTIC:{"document_id":44,"exists":false}\n',
        )
        with patch.object(mod.subprocess, "run", return_value=proc):
            self.assertFalse(mod.inspect(44, "a.pdf", "a" * 64, "thomas")["exists"])

    def test_inspect_rejects_wrong_document_id(self):
        proc = SimpleNamespace(
            returncode=0,
            stdout='BP_IMPORT_DIAGNOSTIC:{"document_id":45,"exists":false}\n',
        )
        with patch.object(mod.subprocess, "run", return_value=proc):
            with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_DOCUMENT_ID"):
                mod.inspect(44, "a.pdf", "a" * 64, "thomas")

    def test_inspect_rejects_query_failure(self):
        proc = SimpleNamespace(returncode=1, stdout="")
        with patch.object(mod.subprocess, "run", return_value=proc):
            with self.assertRaisesRegex(RuntimeError, "DOCUMENT_LOOKUP_FAILED"):
                mod.inspect(44, "a.pdf", "a" * 64, "thomas")

    def test_playbook_is_read_only(self):
        play = PLAY.read_text()
        self.assertIn("changed_when: false", play)
        self.assertIn("diagnose_paperless_import_7a92.py", play)
        self.assertIn("NO_FILES_CHANGED", play)
        self.assertNotIn("paperless_user_deletion_journal_apply_approved", play)
        self.assertNotIn("publish_deleted_by_user_journal.py", play)


if __name__ == "__main__":
    unittest.main()
