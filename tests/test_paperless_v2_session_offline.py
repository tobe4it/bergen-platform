"""Offline-only orchestration tests; all writable paths are temporary fixtures."""
import hashlib
import os
import stat
import sys
import tempfile
import unittest
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "ansible/files/paperless"
sys.path.insert(0, str(SRC))
import v2_sender_session_offline as session
import synology_receipt_v2_store as store
from synology_receipt_versions import legacy_id

PDF = b"%PDF-1.4\n1 0 obj\n(offline test only)\nendobj\n%%EOF\n"
SCOPE = "Familie"
SOURCE_NAME = "Gescanntes Dokument.pdf"


class OfflineSessionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.journal = self.root / "state"
        self.journal.mkdir(mode=0o700)
        self.journal.chmod(0o700)
        self.lock = self.journal / "sync.lock"
        self.lock.write_bytes(b"")
        self.lock.chmod(0o600)
        self.source = self.root / SOURCE_NAME
        self.source.write_bytes(PDF)
        self.source.chmod(0o600)
        self.calls = []
        self.prepared_seen = None

    def receipts(self):
        return sorted(p for p in self.journal.iterdir() if p.name != "sync.lock")

    def prepared_events(self):
        return [p for p in self.receipts() if p.name.endswith(".prepared.json")]

    def transport(self, snapshot, prepared):
        self.calls.append("transport")
        self.prepared_seen = dict(prepared)
        receipt = self.journal / (prepared["receipt_id"] + ".prepared.json")
        self.assertTrue(receipt.is_file(), "PREPARED must precede first callback")
        self.assertEqual(receipt.read_bytes(), store._canonical(prepared))
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(snapshot.read_bytes(), PDF)
        self.assertIn(prepared["incarnation_nonce"], prepared["destination"])
        dest = prepared["destination"].rsplit("/", 1)[1]
        return (0, "sending incremental file list\n"
                "<f+++++++++ " + dest + "\n\n"
                "sent 500 bytes  received 35 bytes  123.45 bytes/sec\n"
                "total size is 64  speedup is 0.12\n", "")

    def receiver(self, prepared):
        self.calls.append("receiver")
        self.assertIsNotNone(self.prepared_seen)
        self.assertEqual(prepared, self.prepared_seen)
        scope, filename = prepared["destination"].rsplit("/", 1)
        expected_bytes = prepared["signature"][2]
        binding = hashlib.sha256(
            (scope + "\0" + filename + "\0" + prepared["sha256"] +
             "\0" + str(expected_bytes)).encode("utf-8")
        ).hexdigest()
        return 0, "\n".join([
            "RECEIVER_BINDING " + binding,
            "RECEIVER_SHA256 " + prepared["sha256"],
            "RECEIVER_BYTES " + str(expected_bytes),
            "RECEIVER_POINT_IN_TIME_VERIFIED",
            "NEW_FILE_NOT_ATTESTED",
            "PAPERLESS_IMPORT_NOT_ATTESTED",
            "SENT_NOT_AUTHORIZED",
            "SOURCE_DELETE_NOT_AUTHORIZED",
            "NO_FILES_CHANGED",
        ]) + "\n"

    def execute_session(self, transport=None, receiver=None):
        return session.run_offline_once(
            self.journal, self.source, SCOPE,
            transport or self.transport, receiver or self.receiver)

    def test_unittest_run_entrypoint_is_not_shadowed(self):
        # TestCase.run is the unittest framework's own lifecycle hook.
        self.assertIs(OfflineSessionTests.run, unittest.TestCase.run)

    def test_complete_matching_mock_session_never_writes_sent(self):
        result = self.execute_session()
        self.assertEqual(self.calls, ["transport", "receiver"])
        self.assertEqual(len(self.prepared_events()), 1)
        self.assertFalse(any(p.name.endswith(".sent.json") for p in self.receipts()))
        self.assertEqual(result["session_status"], "UNRESOLVED_AWAITING_TRUSTED_ORCHESTRATOR")
        self.assertTrue(result["prepared_persisted"])
        self.assertIs(result["origin_authenticated"], False)
        self.assertIs(result["sent_authorized"], False)
        self.assertIs(result["source_delete_authorized"], False)
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_repeated_call_rejected_without_even_invoking_mock(self):
        self.execute_session()
        calls = list(self.calls)
        with self.assertRaisesRegex(RuntimeError, "EXISTING_RECEIPT_BLOCKS_RETRANSMISSION"):
            self.execute_session()
        self.assertEqual(self.calls, calls)
        self.assertEqual(len(self.prepared_events()), 1)

    def test_crash_during_transport_keeps_prepared_and_blocks_retry(self):
        def crash(snapshot, prepared):
            self.calls.append("transport")
            self.assertTrue(self.prepared_events())
            raise KeyboardInterrupt("injected crash")
        with self.assertRaises(KeyboardInterrupt):
            self.execute_session(transport=crash)
        self.assertEqual(self.calls, ["transport"])
        self.assertEqual(len(self.prepared_events()), 1)
        with self.assertRaisesRegex(RuntimeError, "EXISTING_RECEIPT_BLOCKS_RETRANSMISSION"):
            self.execute_session()
        self.assertEqual(self.calls, ["transport"])

    def test_failed_rsync_returncode_keeps_prepared_without_receiver(self):
        def failure(snapshot, prepared):
            self.calls.append("transport")
            return (23, "", "")
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_RSYNC_NOT_VERIFIED"):
            self.execute_session(transport=failure)
        self.assertEqual(self.calls, ["transport"])
        self.assertEqual(len(self.prepared_events()), 1)
        self.assertFalse(any(p.name.endswith(".sent.json") for p in self.receipts()))

    def test_rsync_zero_exit_without_new_file_marker_blocks_receiver(self):
        def ambiguous(snapshot, prepared):
            self.calls.append("transport")
            return (0, "sending incremental file list\n", "")
        with self.assertRaisesRegex(ValueError, "RSYNC_NEW_FILE_MARKER"):
            self.execute_session(transport=ambiguous)
        self.assertEqual(self.calls, ["transport"])
        self.assertEqual(len(self.prepared_events()), 1)

    def test_rsync_wrong_item_direction_blocks_receiver(self):
        def wrong(snapshot, prepared):
            rc, out, err = self.transport(snapshot, prepared)
            return rc, out.replace("<f+++++++++", ">f+++++++++"), err
        with self.assertRaisesRegex(ValueError, "RSYNC_NEW_FILE_MARKER"):
            self.execute_session(transport=wrong)
        self.assertEqual(self.calls, ["transport"])

    def test_receiver_timeout_leaves_unresolved_prepared(self):
        def timeout(prepared):
            self.calls.append("receiver")
            raise TimeoutError("offline simulated timeout")
        with self.assertRaises(TimeoutError):
            self.execute_session(receiver=timeout)
        self.assertEqual(self.calls, ["transport", "receiver"])
        self.assertEqual(len(self.prepared_events()), 1)
        with self.assertRaisesRegex(RuntimeError, "EXISTING_RECEIPT_BLOCKS_RETRANSMISSION"):
            self.execute_session()

    def test_receiver_wrong_hash_leaves_prepared_unresolved(self):
        def corrupted(prepared):
            rc, out = self.receiver(prepared)
            return rc, out.replace(prepared["sha256"], "f" * 64)
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
            self.execute_session(receiver=corrupted)
        self.assertEqual(len(self.prepared_events()), 1)
        self.assertFalse(any(p.name.endswith(".sent.json") for p in self.receipts()))

    def test_forged_receiver_binding_never_authorizes(self):
        def wrong_nonce(prepared):
            rc, out = self.receiver(prepared)
            return rc, out.replace(out.splitlines()[0], "RECEIVER_BINDING " + "1" * 64)
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
            self.execute_session(receiver=wrong_nonce)

    def test_changed_source_after_rsync_blocks_receiver(self):
        def change(snapshot, prepared):
            result = self.transport(snapshot, prepared)
            self.source.write_bytes(PDF + b"appended")
            return result
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_SOURCE_CHANGED_AFTER_TRANSFER"):
            self.execute_session(transport=change)
        self.assertEqual(self.calls, ["transport"])
        self.assertEqual(len(self.prepared_events()), 1)

    def test_snapshot_modified_by_transport_blocks_receiver(self):
        def mutate(snapshot, prepared):
            result = self.transport(snapshot, prepared)
            snapshot.write_bytes(PDF + b"spoofed")
            return result
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_SNAPSHOT_CHANGED"):
            self.execute_session(transport=mutate)
        self.assertEqual(self.calls, ["transport"])
        self.assertEqual(len(self.prepared_events()), 1)

    def test_snapshot_modified_during_receiver_blocks_completion(self):
        retained = []
        def transport(snapshot, prepared):
            retained.append(snapshot)
            return self.transport(snapshot, prepared)
        def receiver(prepared):
            result = self.receiver(prepared)
            retained[0].write_bytes(PDF + b"spoofed")
            return result
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_SNAPSHOT_CHANGED"):
            self.execute_session(transport=transport, receiver=receiver)
        self.assertEqual(self.calls, ["transport", "receiver"])
        self.assertEqual(len(self.prepared_events()), 1)

    def test_changed_source_during_receiver_blocks_complete_result(self):
        def change(prepared):
            result = self.receiver(prepared)
            self.source.write_bytes(PDF + b"appended")
            return result
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_SOURCE_CHANGED_AFTER_TRANSFER"):
            self.execute_session(receiver=change)
        self.assertEqual(self.calls, ["transport", "receiver"])
        self.assertFalse(any(p.name.endswith(".sent.json") for p in self.receipts()))

    def test_prepared_tampering_after_transport_rejected(self):
        def tamper(snapshot, prepared):
            result = self.transport(snapshot, prepared)
            receipt = self.prepared_events()[0]
            receipt.write_bytes(b"altered")
            return result
        with self.assertRaisesRegex(RuntimeError, "PREPARED_CHANGED_AFTER_RSYNC"):
            self.execute_session(transport=tamper)
        self.assertEqual(self.calls, ["transport"])

    def test_prepared_tampering_after_receiver_rejected(self):
        def tamper(prepared):
            result = self.receiver(prepared)
            self.prepared_events()[0].write_bytes(b"altered")
            return result
        with self.assertRaisesRegex(RuntimeError, "PREPARED_CHANGED_AFTER_RECEIVER"):
            self.execute_session(receiver=tamper)

    def test_receiver_failure_returncode_blocks_success(self):
        def failure(prepared):
            rc, stdout = self.receiver(prepared)
            return 1, stdout
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROCESS_UNSUCCESSFUL"):
            self.execute_session(receiver=failure)
        self.assertEqual(len(self.prepared_events()), 1)

    def test_v1_receipt_blocks_new_nonce_and_callback(self):
        from synology_receipt_versions import legacy_id
        path = self.journal / (legacy_id(SCOPE, SOURCE_NAME) + ".json")
        sha = hashlib.sha256(PDF).hexdigest()
        stem = Path(SOURCE_NAME).stem
        item = dict(scope=SCOPE, source=SOURCE_NAME, status="SENT", sha256=sha,
                    signature=[1, 2, len(PDF), 3, 4],
                    destination=SCOPE + "/" + stem + "--nas-" + sha + ".pdf")
        import json
        path.write_text(json.dumps(item), encoding="utf-8")
        path.chmod(0o600)
        original = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "EXISTING_RECEIPT_BLOCKS_RETRANSMISSION"):
            self.execute_session()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.prepared_events())

    def test_symlinked_source_rejected_before_reservation(self):
        target = self.root / "actual.pdf"
        target.write_bytes(PDF)
        target.chmod(0o600)
        self.source.unlink()
        self.source.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OFFLINE_SOURCE"):
            self.execute_session()
        self.assertFalse(self.prepared_events())
        self.assertEqual(self.calls, [])

    def test_hardlinked_source_rejected_before_reservation(self):
        other = self.root / "other.pdf"
        os.link(self.source, other)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OFFLINE_SOURCE"):
            self.execute_session()
        self.assertFalse(self.prepared_events())

    def test_publicly_readable_source_rejected(self):
        self.source.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OFFLINE_SOURCE"):
            self.execute_session()
        self.assertFalse(self.prepared_events())

    def test_not_pdf_rejected_without_journal(self):
        self.source.write_bytes(b"Definitely no PDF")
        with self.assertRaisesRegex(RuntimeError, "INVALID_OFFLINE_PDF"):
            self.execute_session()
        self.assertFalse(self.prepared_events())

    def test_wrong_scope_rejected_without_journal(self):
        with self.assertRaises(ValueError):
            session.run_offline_once(self.journal, self.source, "../Familie",
                                     self.transport, self.receiver)
        self.assertFalse(self.prepared_events())

    def test_unknown_well_formed_scope_is_not_approved(self):
        with self.assertRaisesRegex(ValueError, "UNAPPROVED_OFFLINE_SCOPE"):
            session.run_offline_once(self.journal, self.source, "Other",
                                     self.transport, self.receiver)
        self.assertFalse(self.prepared_events())

    def test_unexpected_transport_callback_shape_blocks_receiver(self):
        def malformed(snapshot, prepared):
            self.calls.append("transport")
            return (0, "OK")
        with self.assertRaisesRegex(ValueError, "INVALID_TRANSPORT_CALLBACK"):
            self.execute_session(transport=malformed)
        self.assertEqual(self.calls, ["transport"])
        self.assertEqual(len(self.prepared_events()), 1)

    def test_unexpected_receiver_callback_shape_blocks_success(self):
        def malformed(prepared):
            self.calls.append("receiver")
            return "SUCCESS"
        with self.assertRaisesRegex(ValueError, "INVALID_RECEIVER_CALLBACK"):
            self.execute_session(receiver=malformed)
        self.assertEqual(self.calls, ["transport", "receiver"])
        self.assertEqual(len(self.prepared_events()), 1)

    def test_sender_lock_stays_held_during_both_callbacks(self):
        def assert_lock():
            fd = os.open(self.lock, os.O_RDONLY)
            try:
                with self.assertRaises(BlockingIOError):
                    flock(fd, LOCK_EX | LOCK_NB)
            finally:
                os.close(fd)
        def t(snapshot, prepared):
            assert_lock()
            return self.transport(snapshot, prepared)
        def r(prepared):
            assert_lock()
            return self.receiver(prepared)
        result = self.execute_session(transport=t, receiver=r)
        self.assertFalse(result["sent_authorized"])

    def test_existing_exclusive_lock_blocks_reservation(self):
        fd = os.open(self.lock, os.O_RDONLY)
        try:
            flock(fd, LOCK_EX | LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.execute_session()
        finally:
            flock(fd, LOCK_UN)
            os.close(fd)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.prepared_events())

    def test_unexpected_orphan_blocks_before_snapshot_or_transport(self):
        orphan = self.journal / ".v2-receipt-old.tmp"
        orphan.write_bytes(b"uncertain crash")
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN_OR_ORPHANED_JOURNAL_ENTRY"):
            self.execute_session()
        self.assertEqual(self.calls, [])
        self.assertEqual(orphan.read_bytes(), b"uncertain crash")
        self.assertFalse(self.prepared_events())

    def test_no_liveness_or_prod_sender_entrypoint(self):
        code = (SRC / "v2_sender_session_offline.py").read_text()
        self.assertIn("OFFLINE ONLY", code)
        for forbidden in ('if __name__ == "__main__"', "subprocess.run(",
                          "ssh -i", "rsync -", "pct exec", "os.unlink(source",
                          "sent_record(", "publish_event(", "source.unlink("):
            self.assertNotIn(forbidden, code)
        active = (SRC / "synology_scan_sync.py").read_text()
        self.assertNotIn("v2_sender_session_offline", active)
        self.assertNotIn("compare_v2_transfer_evidence_offline", active)


if __name__ == "__main__":
    unittest.main()
