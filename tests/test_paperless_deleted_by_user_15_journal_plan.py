"""Offline tests for second immutable DELETED_BY_USER journal *dry-run only*."""
import hashlib
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SOURCE))


def module(filename, name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


schema = module("deleted_by_user_15_decision_journal.py", "deleted_by_user_15_schema")
target = module("plan_deleted_by_user_15_journal_target.py", "deleted_by_user_15_target")
OLD_SCHEMA = module("deleted_by_user_decision_journal.py", "deleted_by_user_26_schema")
DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
RECEIVER = "Privat/thomas/Gebuehren--nas-" + DIGEST + ".pdf"
NAS = {
    "schema_version": 1,
    "sender_receipt": "adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json",
    "scope": "Privat/thomas", "source": "Gebuehren.pdf",
    "receiver_source": RECEIVER, "sha256": DIGEST,
    "sender_status": "SENT", "nas_original_absent": True,
}
DELETED = {
    "schema_version": 1,
    "bridge_receipt": "7a92b91deb7b2e8e35f9f710.json",
    "document_id": 15, "receiver_source": RECEIVER,
    "sha256": DIGEST, "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}


class Document15JournalDryRunTests(unittest.TestCase):
    def test_builds_exact_pinned_event_and_payload(self):
        record = schema.build(NAS, DELETED)
        self.assertEqual(record["document_id"], 15)
        self.assertEqual(record["event_id"], schema.EXPECTED_EVENT)
        self.assertEqual(hashlib.sha256(schema.canonical(record)).hexdigest(),
                         schema.EXPECTED_PAYLOAD_HASH)
        self.assertEqual(target.validate(record), schema.canonical(record))

    def test_distinct_from_document_26_even_with_identical_sha(self):
        record = schema.build(NAS, DELETED)
        old = OLD_SCHEMA.build({
            "schema_version": 1, "sender_receipt": OLD_SCHEMA.SENDER,
            "scope": OLD_SCHEMA.SCOPE, "source": OLD_SCHEMA.SOURCE,
            "receiver_source": "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf",
            "sha256": DIGEST, "sender_status": "SENT",
            "nas_original_absent": True,
        }, {
            "schema_version": 1, "bridge_receipt": OLD_SCHEMA.BRIDGE,
            "document_id": 26,
            "receiver_source": "Privat/thomas/Gebuehren 2--nas-" + DIGEST + ".pdf",
            "sha256": DIGEST, "proposed_status": "DELETED_IN_PAPERLESS",
            "live_document_absent": True, "original_filename_absent": True,
        })
        self.assertNotEqual(record["event_id"], old["event_id"])
        self.assertNotEqual(record["bridge_receipt"], old["bridge_receipt"])
        self.assertNotEqual(record["sender_receipt"], old["sender_receipt"])
        self.assertEqual(record["sha256"], old["sha256"])

    def test_preview_does_not_write(self):
        output = io.StringIO()
        with redirect_stdout(output):
            schema.preview(json.dumps(NAS) + "\nNO_FILES_CHANGED", json.dumps(DELETED))
        self.assertIn("PROPOSED_USER_DELETION_JOURNAL_FILENAME " + schema.EXPECTED_EVENT, output.getvalue())
        self.assertIn("NO_JOURNAL_WRITTEN", output.getvalue())
        self.assertIn("NO_FILES_CHANGED", output.getvalue())

    def test_missing_nas_readonly_marker_blocks(self):
        with self.assertRaisesRegex(ValueError, "MISSING_READ_ONLY_NAS_MARKER"):
            schema.preview(json.dumps(NAS), json.dumps(DELETED))

    def test_document_id_changed_blocks(self):
        with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
            schema.build(NAS, dict(DELETED, document_id=26))

    def test_wrong_sender_receipt_blocks(self):
        with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
            schema.build(dict(NAS, sender_receipt=OLD_SCHEMA.SENDER), DELETED)

    def test_wrong_bridge_receipt_blocks(self):
        with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
            schema.build(NAS, dict(DELETED, bridge_receipt=OLD_SCHEMA.BRIDGE))

    def test_original_still_present_blocks(self):
        with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
            schema.build(dict(NAS, nas_original_absent=False), DELETED)

    def test_paperless_document_present_blocks(self):
        with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
            schema.build(NAS, dict(DELETED, live_document_absent=False))

    def test_filename_present_blocks(self):
        with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
            schema.build(NAS, dict(DELETED, original_filename_absent=False))

    def test_digest_changed_even_on_both_sides_blocks(self):
        other = "a" * 64
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_FIELDS"):
            schema.build(dict(NAS, sha256=other,
                              receiver_source="Privat/thomas/Gebuehren--nas-" + other + ".pdf"),
                         dict(DELETED, sha256=other,
                              receiver_source="Privat/thomas/Gebuehren--nas-" + other + ".pdf"))

    def test_wrong_journal_event_blocks(self):
        record = schema.build(NAS, DELETED)
        with self.assertRaisesRegex(ValueError, "USER_DELETION_EVENT_ID_MISMATCH"):
            schema.validate(dict(record, event_id="a" * 64))

    def test_wrong_confirmation_blocks(self):
        record = schema.build(NAS, DELETED)
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_FIELDS"):
            schema.validate(dict(record, confirmation_date="2026-10-15"))

    def test_target_rejects_other_journal_identity(self):
        with self.assertRaisesRegex(RuntimeError, "UNEXPECTED_USER_DELETION_TARGET"):
            target.validate(dict(schema.build(NAS, DELETED), document_id=26))

    def test_no_write_primitive_in_new_scripts(self):
        for filename in ("deleted_by_user_15_decision_journal.py",
                         "plan_deleted_by_user_15_journal_target.py"):
            src = (SOURCE / filename).read_text()
            for forbidden in ("os.unlink(", "os.replace(", "os.mkdir(",
                              "os.chmod(", "os.chown(", "publish_once(",
                              "os.link(", ".write_text(", ".write_bytes("):
                self.assertNotIn(forbidden, src)

    def test_playbook_is_readonly_with_new_evidence_and_previous_journal(self):
        play = (ROOT / "ansible/playbooks/plan-paperless-deleted-by-user-15-journal.yml").read_text()
        self.assertIn("preview_deleted_import_15.py", play)
        self.assertIn("diagnose_deleted_import_15_nas.py", play)
        self.assertIn("deleted_by_user_15_decision_journal.py", play)
        self.assertIn("plan_deleted_by_user_15_journal_target.py", play)
        self.assertIn("export_verified_user_deletion_journal.py", play)
        self.assertIn("changed_when: false", play)
        self.assertNotIn("publish_deleted_by_user_journal.py", play)
        self.assertNotIn("paperless_user_deletion_journal_apply_approved", play)
        self.assertNotIn("ARCHIVE_MATCH_READY", play)

    def test_storage_plan_requires_private_directory_and_restricted_user(self):
        source = (SOURCE / "plan_deleted_by_user_15_journal_target.py").read_text()
        self.assertIn("EXPECTED_UID = 997", source)
        self.assertIn("EXPECTED_GID = 988", source)
        self.assertIn("0o700", source)
        self.assertIn("0o600", source)
        self.assertIn("O_NOFOLLOW", source)
        self.assertIn("READY_TO_PUBLISH", source)


if __name__ == "__main__":
    unittest.main()
