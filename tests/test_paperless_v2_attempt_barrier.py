"""Offline tests for the irreversible v2 ATTEMPTED transport barrier."""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(CODE))
import synology_receipt_v2_store as store

spec = importlib.util.spec_from_file_location(
    "staged_history_auditor", CODE / "audit_synology_receipt_history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)

SHA = hashlib.sha256(b"%PDF-1.4\noffline\n%%EOF\n").hexdigest()
SIG = [42, 81, 26, 500, 600]
SCOPE = "Familie"


class AttemptBarrierTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.state = Path(t.name)
        self.state.chmod(0o700)
        lock = self.state / "sync.lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        self.prepared = store.prepared_record(
            SCOPE, "One.pdf", SHA, SIG, "a" * 32)
        self.attempted = store.attempted_record(self.prepared)
        self.pfile = self.state / (self.prepared["receipt_id"] + ".prepared.json")
        self.afile = self.state / (self.prepared["receipt_id"] + ".attempted.json")

    def publish_both(self):
        store.publish_event(self.state, self.prepared)
        return store.publish_event(self.state, self.attempted)

    def check_history(self):
        return history.audit_directory(self.state, (SCOPE,))

    def test_attempt_has_same_identity_and_exact_schema(self):
        self.assertEqual(self.attempted["status"], "ATTEMPTED")
        self.assertEqual(self.attempted["receipt_id"], self.prepared["receipt_id"])
        self.assertEqual(self.attempted["destination"], self.prepared["destination"])
        self.assertEqual(set(self.attempted), set(self.prepared))

    def test_attempt_without_prepared_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            store.publish_event(self.state, self.attempted)
        self.assertFalse(self.afile.exists())

    def test_attempt_creation_after_prepared_is_durable(self):
        result = self.publish_both()
        self.assertEqual(result, (self.afile, True))
        self.assertEqual(self.pfile.read_bytes(), store._canonical(self.prepared))
        self.assertEqual(self.afile.read_bytes(), store._canonical(self.attempted))
        self.assertEqual(self.afile.stat().st_nlink, 1)
        self.assertEqual(self.afile.stat().st_mode & 0o777, 0o600)

    def test_attempt_must_never_be_published_twice(self):
        self.publish_both()
        original = self.afile.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "TRANSFER_ATTEMPT_ALREADY_RECORDED"):
            store.publish_event(self.state, self.attempted)
        self.assertEqual(self.afile.read_bytes(), original)

    def test_attempt_prepared_nonce_mismatch_rejected(self):
        store.publish_event(self.state, self.prepared)
        altered = dict(self.attempted, incarnation_nonce="b" * 32)
        with self.assertRaisesRegex(ValueError, "EVENT_ID_OR_DESTINATION_MISMATCH"):
            store.publish_event(self.state, altered)
        self.assertFalse(self.afile.exists())

    def test_attempted_cannot_be_derived_from_sent(self):
        sent = store.sent_record(self.prepared, {
            "receiver_source": self.prepared["destination"],
            "receiver_sha256": SHA, "new_file_confirmed": True})
        with self.assertRaisesRegex(ValueError, "PREPARED_EVENT_REQUIRED"):
            store.attempted_record(sent)

    def test_history_auditor_counts_attempt_and_unresolved(self):
        self.publish_both()
        result = self.check_history()
        self.assertEqual(result["total_receipts"], 2)
        self.assertEqual(result["counts"][SCOPE]["v2_attempted"], 1)
        self.assertEqual(result["counts"][SCOPE]["v2_prepared"], 1)
        self.assertEqual(result["unresolved"], 1)
        self.assertFalse(result["can_archive"])

    def test_store_history_blocks_nonce_reallocation_after_attempt(self):
        self.publish_both()
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_NAME_REQUIRES_RECONCILIATION"):
            store.reserve_prepared(self.state, SCOPE, "One.pdf", SHA, SIG)
        self.assertEqual(self.afile.read_bytes(), store._canonical(self.attempted))

    def test_orphan_attempt_rejected_by_both_auditors(self):
        self.afile.write_bytes(store._canonical(self.attempted))
        self.afile.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "ATTEMPTED_WITHOUT_PREPARED"):
            self.check_history()
        with self.assertRaisesRegex(RuntimeError, "ATTEMPTED_WITHOUT_PREPARED"):
            store.reserve_prepared(self.state, SCOPE, "Two.pdf", SHA, SIG)

    def test_tampered_attempt_rejected_by_history(self):
        self.publish_both()
        altered = json.loads(self.afile.read_bytes())
        altered["incarnation_nonce"] = "b" * 32
        self.afile.write_bytes((json.dumps(altered, sort_keys=True, separators=(",", ":")) + "\n").encode())
        with self.assertRaisesRegex(RuntimeError, "INVALID_V2_RECEIPT_IDENTITY"):
            self.check_history()
        with self.assertRaisesRegex(RuntimeError, "INVALID_HISTORICAL_RECEIPT"):
            store.reserve_prepared(self.state, SCOPE, "Two.pdf", SHA, SIG)

    def test_same_event_cannot_be_substituted_for_prepared(self):
        self.afile.write_bytes(store._canonical(self.attempted))
        self.afile.chmod(0o600)
        self.pfile.write_bytes(store._canonical(self.attempted))
        self.pfile.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "V2_STATUS_MISMATCH"):
            store.reserve_prepared(self.state, SCOPE, "Two.pdf", SHA, SIG)

    def test_existing_legacy_receipt_bytes_remain_unchanged(self):
        legacy = store.legacy_id(SCOPE, "Legacy.pdf") + ".json"
        path = self.state / legacy
        item = dict(scope=SCOPE, source="Legacy.pdf", status="SENT",
                    sha256=SHA, signature=SIG,
                    destination=SCOPE + "/Legacy--nas-" + SHA + ".pdf")
        path.write_text(json.dumps(item))
        path.chmod(0o600)
        before = path.read_bytes()
        self.publish_both()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.check_history()["counts"][SCOPE]["v1_sent"], 1)

    def test_no_live_sender_integration(self):
        active = (CODE / "synology_scan_sync.py").read_text()
        self.assertNotIn("attempted_record", active)
        self.assertNotIn("v2_sender_session_offline", active)


if __name__ == "__main__":
    unittest.main()
