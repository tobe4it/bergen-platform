"""Offline-only deletion journal schema, immutability, and crash-safety tests."""
import copy
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless/deleted_import_decision_journal.py"
spec = importlib.util.spec_from_file_location("deleted_journal", SOURCE)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)

SHA = "a" * 64
BRIDGE = "b" * 24 + ".json"
SENDER = "c" * 64 + ".json"
DEST = "Privat/thomas/Gebuehren 2--nas-" + SHA + ".pdf"
NAS = {
    "sender_receipt": SENDER, "scope": "Privat/thomas",
    "source": "Gebuehren 2.pdf", "receiver_source": DEST, "sha256": SHA,
}
DELETED = {
    "schema_version": 1, "bridge_receipt": BRIDGE, "document_id": 26,
    "receiver_source": DEST, "sha256": SHA,
    "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}


def decision():
    return journal.build_record(
        NAS, DELETED, "thomas",
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        26, BRIDGE,
    )


class DeletedDecisionJournalTests(unittest.TestCase):
    def test_schema_binds_all_identifiers(self):
        rec = decision()
        self.assertEqual(rec["event"], "DELETED_IN_PAPERLESS")
        self.assertEqual(rec["sender_receipt"], SENDER)
        self.assertEqual(rec["bridge_receipt"], BRIDGE)
        self.assertEqual(rec["document_id"], 26)
        self.assertEqual(rec["sha256"], SHA)
        self.assertEqual(rec["event_id"], journal.validate_record(rec))

    def test_atomic_create_and_idempotent_repeat(self):
        rec = decision()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            os.chmod(folder, 0o700)
            target, created = journal.write_decision(folder, rec)
            self.assertTrue(created)
            self.assertEqual(target.parent, folder)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(json.loads(target.read_text()), rec)
            self.assertEqual(journal.write_decision(folder, rec), (target, False))
            self.assertEqual(list(folder.iterdir()), [target])

    def test_same_identity_different_confirmation_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            os.chmod(folder, 0o700)
            first = decision()
            path, _ = journal.write_decision(folder, first)
            second = copy.deepcopy(first)
            second["confirmed_by"] = "another-operator"
            with self.assertRaisesRegex(RuntimeError, "CONFLICTING_DECISION"):
                journal.write_decision(folder, second)
            self.assertEqual(json.loads(path.read_text()), first)

    def test_existing_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            os.chmod(folder, 0o700)
            rec = decision()
            target = folder / (rec["event_id"] + ".json")
            other = folder / "other.json"
            other.write_text("do not change")
            target.symlink_to(other)
            with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING_DECISION"):
                journal.write_decision(folder, rec)
            self.assertEqual(other.read_text(), "do not change")

    def test_unsafe_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            os.chmod(folder, 0o755)
            with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
                journal.write_decision(folder, decision())

    def test_modified_digest_rejected(self):
        rec = decision()
        rec["sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "INVALID_DECISION_FIELDS"):
            journal.validate_record(rec)

    def test_modified_document_id_rejected(self):
        rec = decision()
        rec["document_id"] = 27
        with self.assertRaisesRegex(ValueError, "DECISION_IDENTITY_MISMATCH"):
            journal.validate_record(rec)

    def test_unapproved_document_rejected(self):
        with self.assertRaisesRegex(ValueError, "DELETION_PROOF_OR_APPROVAL_MISMATCH"):
            journal.build_record(NAS, DELETED, "thomas", decision()["confirmed_at"], 27, BRIDGE)

    def test_live_document_still_present_rejected(self):
        d = dict(DELETED, live_document_absent=False)
        with self.assertRaisesRegex(ValueError, "DELETION_PROOF_OR_APPROVAL_MISMATCH"):
            journal.build_record(NAS, d, "thomas", decision()["confirmed_at"], 26, BRIDGE)

    def test_nas_digest_mismatch_rejected(self):
        n = dict(NAS, sha256="d" * 64)
        with self.assertRaisesRegex(ValueError, "DELETION_PROOF_OR_APPROVAL_MISMATCH"):
            journal.build_record(n, DELETED, "thomas", decision()["confirmed_at"], 26, BRIDGE)

    def test_non_utc_confirmation_rejected(self):
        rec = decision()
        rec["confirmed_at"] = "2026-10-14T21:39:00+02:00"
        with self.assertRaisesRegex(ValueError, "CONFIRMATION_TIME_NOT_UTC"):
            journal.validate_record(rec)

    def test_no_production_entrypoint(self):
        source = SOURCE.read_text(encoding="utf-8")
        compile(source, str(SOURCE), "exec")
        self.assertNotIn('if __name__ == "__main__"', source)
        self.assertNotIn("/srv/bergen-paperless", source)
        self.assertNotIn("/volume1", source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn(".unlink(", source)


if __name__ == "__main__":
    unittest.main()
