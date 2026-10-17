"""Offline regression tests for two-sided deletion decision schema."""
import copy
import hashlib
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/deleted_by_user_decision_journal.py"
spec = importlib.util.spec_from_file_location("deleted_by_user_decision_journal", SRC)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)
DIGEST = "a" * 64
RECEIVER = "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf"
NAS = {
    "schema_version": 1, "sender_receipt": journal.SENDER,
    "scope": journal.SCOPE, "source": journal.SOURCE,
    "receiver_source": RECEIVER, "sha256": DIGEST,
    "sender_status": "SENT", "nas_original_absent": True,
}
DELETED = {
    "schema_version": 1, "bridge_receipt": journal.BRIDGE,
    "document_id": 26, "receiver_source": RECEIVER,
    "sha256": DIGEST, "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}


class UserDeletionDecisionJournalTests(unittest.TestCase):
    def test_valid_journal_record(self):
        rec = journal.build(NAS, DELETED)
        self.assertEqual(rec["event"], "DELETED_BY_USER")
        self.assertEqual(rec["schema_version"], 2)
        self.assertEqual(rec["document_id"], 26)
        self.assertEqual(rec["event_id"], journal.validate(rec))
        self.assertEqual(rec["confirmation_method"], "explicit_user_chat")

    def test_stable_event_id(self):
        self.assertEqual(journal.build(NAS, DELETED), journal.build(NAS, DELETED))

    def test_canonical_checksum(self):
        rec = journal.build(NAS, DELETED)
        self.assertEqual(len(hashlib.sha256(journal.canonical(rec)).hexdigest()), 64)

    def test_nas_original_present_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(dict(NAS, nas_original_absent=False), DELETED)

    def test_sender_prepared_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(dict(NAS, sender_status="PREPARED"), DELETED)

    def test_wrong_digest_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(dict(NAS, sha256="b" * 64), DELETED)

    def test_wrong_receiver_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(dict(NAS, receiver_source="other.pdf"), DELETED)

    def test_wrong_document_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(NAS, dict(DELETED, document_id=27))

    def test_live_paperless_document_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(NAS, dict(DELETED, live_document_absent=False))

    def test_live_original_filename_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(NAS, dict(DELETED, original_filename_absent=False))

    def test_wrong_sender_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(dict(NAS, sender_receipt="b" * 64 + ".json"), DELETED)

    def test_unknown_evidence_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "LIVE_EVIDENCE_MISMATCH"):
            journal.build(dict(NAS, extra=True), DELETED)

    def test_event_change_rejected(self):
        rec = journal.build(NAS, DELETED)
        rec["event"] = "DELETED_IN_PAPERLESS"
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_FIELDS"):
            journal.validate(rec)

    def test_identity_mutation_rejected(self):
        rec = journal.build(NAS, DELETED)
        rec["sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_FIELDS"):
            journal.validate(rec)

    def test_confirmation_mutation_rejected(self):
        rec = journal.build(NAS, DELETED)
        rec["confirmation_date"] = "2026-10-15"
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_FIELDS"):
            journal.validate(rec)

    def test_extra_record_field_rejected(self):
        rec = journal.build(NAS, DELETED)
        rec["unauthorized"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_SCHEMA"):
            journal.validate(rec)

    def test_preview_read_only_markers(self):
        out = io.StringIO()
        with redirect_stdout(out):
            journal.preview(json.dumps(NAS) + "\nNO_FILES_CHANGED", json.dumps(DELETED))
        self.assertIn("NO_JOURNAL_WRITTEN", out.getvalue())
        self.assertIn("EXCLUDED_FROM_ARCHIVE_MATCH_READY", out.getvalue())
        self.assertIn("NO_FILES_CHANGED", out.getvalue())
        self.assertIn("REUSED_FILENAME_NEW_INCARNATION_NOT_AUTHORIZED", out.getvalue())

    def test_preview_missing_marker_rejected(self):
        with self.assertRaisesRegex(ValueError, "MISSING_READ_ONLY_NAS_MARKER"):
            journal.preview(json.dumps(NAS), json.dumps(DELETED))

    def test_no_write_or_production_path(self):
        src = SRC.read_text(encoding="utf-8")
        self.assertNotIn("open(", src)
        self.assertNotIn("write_text(", src)
        self.assertNotIn("os.unlink(", src)
        self.assertNotIn("os.replace(", src)
        self.assertNotIn("/volume1", src)
        self.assertNotIn("/srv/bergen-paperless", src)

    def test_old_v1_journal_unmodified(self):
        legacy = (ROOT / "ansible/files/paperless/deleted_import_decision_journal.py").read_text()
        self.assertIn('"DELETED_IN_PAPERLESS"', legacy)
        self.assertIn("def write_decision(", legacy)


if __name__ == "__main__":
    unittest.main()
