"""Offline safety and proof-matching tests for user-confirmed deletion of document 15."""
import hashlib
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless"
MATCH = SOURCE / "preview_deleted_import_15.py"
NAS_SCRIPT = SOURCE / "diagnose_deleted_import_15_nas.py"
PLAY = ROOT / "ansible/playbooks/preview-paperless-deleted-import-15.yml"
spec = importlib.util.spec_from_file_location("deleted_15_policy", MATCH)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

SHA = "a" * 64
SOURCE_NAME = "Test 15.pdf"
DEST = "Privat/thomas/Test 15--nas-" + SHA + ".pdf"
SENDER = hashlib.sha256(b"Privat/thomas\0Test 15.pdf").hexdigest() + ".json"
PAPERLESS = {
    "schema_version": 1, "bridge_receipt": "7a92b91deb7b2e8e35f9f710.json",
    "document_id": 15, "receiver_source": DEST, "sha256": SHA,
    "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}
NAS = {
    "schema_version": 1, "sender_receipt": SENDER,
    "scope": "Privat/thomas", "source": SOURCE_NAME,
    "receiver_source": DEST, "sha256": SHA,
    "sender_status": "SENT", "nas_original_absent": True,
}


def run(paperless=None, nas=None, marker=True):
    stream = io.StringIO()
    with redirect_stdout(stream):
        policy.compare(json.dumps(PAPERLESS if paperless is None else paperless),
                       json.dumps(NAS if nas is None else nas) +
                       ("\nNO_FILES_CHANGED" if marker else ""))
    return stream.getvalue()


class DeletedImport15Tests(unittest.TestCase):
    def test_valid_absence_previews_without_journal(self):
        result = run()
        for expected in (
                "PREVIEW_DELETED_BY_USER 15",
                "NAS_ORIGINAL_FILENAME Test 15.pdf",
                "NO_JOURNAL_WRITTEN",
                "NO_RECEIPTS_CHANGED",
                "ARCHIVE_NOT_AUTHORIZED",
                "NO_FILES_CHANGED"):
            self.assertIn(expected, result)

    def test_missing_nas_marker_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_READ_ONLY_MARKER_MISSING"):
            run(marker=False)

    def test_wrong_document_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_ABSENCE_PROOF"):
            run(paperless=dict(PAPERLESS, document_id=26))

    def test_wrong_bridge_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_ABSENCE_PROOF"):
            run(paperless=dict(PAPERLESS, bridge_receipt="b" * 24 + ".json"))

    def test_live_document_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_ABSENCE_PROOF"):
            run(paperless=dict(PAPERLESS, live_document_absent=False))

    def test_live_filename_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PAPERLESS_ABSENCE_PROOF"):
            run(paperless=dict(PAPERLESS, original_filename_absent=False))

    def test_nas_source_present_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_PAPERLESS_DELETION_PROOF_MISMATCH"):
            run(nas=dict(NAS, nas_original_absent=False))

    def test_sender_not_sent_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_PAPERLESS_DELETION_PROOF_MISMATCH"):
            run(nas=dict(NAS, sender_status="PREPARED"))

    def test_sender_receipt_wrong_key_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_PAPERLESS_DELETION_PROOF_MISMATCH"):
            run(nas=dict(NAS, sender_receipt="b" * 64 + ".json"))

    def test_digest_mismatch_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_PAPERLESS_DELETION_PROOF_MISMATCH"):
            run(nas=dict(NAS, sha256="b" * 64))

    def test_unknown_nas_field_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_PAPERLESS_DELETION_PROOF_MISMATCH"):
            run(nas=dict(NAS, unexpected="value"))

    def test_read_only_nas_script(self):
        src = NAS_SCRIPT.read_text()
        for forbidden in ("os.unlink(", "os.replace(", "os.mkdir(", "os.chmod(",
                          "os.chown(", ".write_text(", ".write_bytes(",
                          "publish_once(", "write_receipt("):
            self.assertNotIn(forbidden, src)
        self.assertIn("LOCK_EX | LOCK_NB", src)
        self.assertIn("NAS_ORIGINAL_STILL_PRESENT", src)
        self.assertIn("SENDER_RECEIPT_MATCH_COUNT_", src)

    def test_read_only_playbook_and_no_archive_gate(self):
        play = PLAY.read_text()
        self.assertIn("changed_when: false", play)
        self.assertIn("export_deleted_import_candidate.py", play)
        self.assertIn("diagnose_deleted_import_15_nas.py", play)
        self.assertIn("preview_deleted_import_15.py", play)
        self.assertNotIn("paperless_user_deletion_journal_apply_approved", play)
        self.assertNotIn("publish_deleted_by_user_journal.py", play)
        self.assertNotIn("ARCHIVE_MATCH_READY", play)


if __name__ == "__main__":
    unittest.main()
