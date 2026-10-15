"""Offline nonce-bound incarnation reservation, no NAS or Paperless access."""
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock

SRC = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(SRC))
import synology_receipt_versions as versions
import synology_receipt_v2_store as store

SCOPE = "Familie"
NAME = "Dokument.pdf"
DIGEST = hashlib.sha256(b"%PDF-1.4 %%EOF").hexdigest()
SIG = [1048641, 456, 1536, 123456, 123457]


class IncarnationPersistenceTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.directory = Path(t.name)
        self.directory.chmod(0o700)
        self.lock = self.directory / "sync.lock"
        self.lock.write_bytes(b"")
        self.lock.chmod(0o600)

    def reserve(self, scope=SCOPE, name=NAME, sha=DIGEST, sig=SIG):
        return store.reserve_prepared(self.directory, scope, name, sha, sig)

    def test_nonce_bound_to_receipt_and_receiver(self):
        nonce1, nonce2 = "1" * 32, "2" * 32
        one = versions.incarnation_id(SCOPE, NAME, DIGEST, SIG, nonce1)
        two = versions.incarnation_id(SCOPE, NAME, DIGEST, SIG, nonce2)
        self.assertNotEqual(one, two)
        self.assertRegex(one, r"\Av2-[a-f0-9]{32}-[a-f0-9]{64}\Z")
        self.assertIn(nonce1, one)
        self.assertIn(nonce1, versions.incarnation_receiver_destination(
            SCOPE, NAME, DIGEST, SIG, nonce1))
        self.assertEqual(versions.incarnation_receipt_filename(
            SCOPE, NAME, DIGEST, SIG, nonce1), one + ".prepared.json")
        self.assertNotEqual(versions.incarnation_receiver_destination(
            SCOPE, NAME, DIGEST, SIG, nonce1),
            versions.incarnation_receiver_destination(
                SCOPE, NAME, DIGEST, SIG, nonce2))

    def test_same_signature_inode_reuse_different_nonce(self):
        self.assertNotEqual(
            versions.incarnation_id(SCOPE, NAME, DIGEST, SIG, "a" * 32),
            versions.incarnation_id(SCOPE, NAME, DIGEST, SIG, "b" * 32))

    def test_reserve_persists_random_nonce_before_return(self):
        path, prepared = self.reserve()
        self.assertEqual(path.read_bytes(), store._canonical(prepared))
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.stat().st_nlink, 1)
        nonce = prepared["incarnation_nonce"]
        self.assertRegex(nonce, r"\A[a-f0-9]{32}\Z")
        self.assertIn(nonce, path.name)
        self.assertIn(nonce, prepared["destination"])
        self.assertEqual(prepared["receipt_id"] + ".prepared.json", path.name)
        self.assertEqual(prepared["status"], "PREPARED")

    def test_restart_never_allocates_a_second_id(self):
        path, record = self.reserve()
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_NAME_REQUIRES_RECONCILIATION"):
            self.reserve()
        self.assertEqual(path.read_bytes(), store._canonical(record))
        self.assertEqual(len(list(self.directory.glob("v2-*.prepared.json"))), 1)

    def test_v1_existing_receipt_blocks_new_nonce(self):
        event_id = versions.legacy_id(SCOPE, NAME)
        old = dict(scope=SCOPE, source=NAME, status="SENT", sha256=DIGEST,
                   signature=SIG, destination=SCOPE + "/Dokument--nas-" + DIGEST + ".pdf")
        path = self.directory / (event_id + ".json")
        path.write_text(json.dumps(old))
        path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_NAME_REQUIRES_RECONCILIATION"):
            self.reserve()
        self.assertEqual(len(list(self.directory.glob("v2-*"))), 0)
        self.assertEqual(json.loads(path.read_text()), old)

    def test_other_source_name_can_be_reserved(self):
        first, _ = self.reserve()
        second, _ = self.reserve(name="Weiteres Dokument.pdf")
        self.assertNotEqual(first, second)

    def test_prepared_to_sent_preserves_incarnation_identity(self):
        path, prepared = self.reserve()
        proof = dict(receiver_source=prepared["destination"], receiver_sha256=DIGEST,
                     new_file_confirmed=True)
        sent = store.sent_record(prepared, proof)
        self.assertEqual(sent["receipt_id"], prepared["receipt_id"])
        self.assertEqual(sent["incarnation_nonce"], prepared["incarnation_nonce"])
        self.assertEqual(store.publish_event(self.directory, sent),
                         (self.directory / (sent["receipt_id"] + ".sent.json"), True))
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_NAME_REQUIRES_RECONCILIATION"):
            self.reserve()
        self.assertEqual(path.read_bytes(), store._canonical(prepared))

    def test_fake_nonce_is_detected_by_store_and_history(self):
        path, prepared = self.reserve()
        forged = dict(prepared, incarnation_nonce="f" * 32)
        with self.assertRaisesRegex(ValueError, "EVENT_ID_OR_DESTINATION_MISMATCH"):
            store.publish_event(self.directory, forged)
        raw = json.loads(path.read_bytes())
        raw["incarnation_nonce"] = "f" * 32
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(RuntimeError, "INVALID_HISTORICAL_RECEIPT"):
            self.reserve()

    def test_orphan_receipt_tmp_blocks_new_allocation(self):
        orphan = self.directory / ".v2-receipt-crashed.tmp"
        orphan.write_bytes(b"unknown")
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN_OR_ORPHANED"):
            self.reserve()
        self.assertFalse(list(self.directory.glob("v2-*.prepared.json")))
        self.assertEqual(orphan.read_bytes(), b"unknown")

    def test_unknown_legacy_json_blocks_allocation(self):
        extra = self.directory / "unexpected.json"
        extra.write_bytes(b"{}")
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN_OR_ORPHANED"):
            self.reserve()

    def test_malformed_legacy_receipt_blocks_allocation(self):
        old = self.directory / (versions.legacy_id(SCOPE, NAME) + ".json")
        old.write_bytes(b'{"scope":"Familie","status":"SENT"}')
        old.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "INVALID_HISTORICAL_RECEIPT"):
            self.reserve()

    def test_lock_contention_does_not_publish(self):
        fd = os.open(self.lock, os.O_RDONLY)
        try:
            flock(fd, LOCK_EX | LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.reserve()
        finally:
            flock(fd, LOCK_UN)
            os.close(fd)
        self.assertFalse(list(self.directory.glob("v2-*.prepared.json")))

    def test_unsafe_directory_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
            self.reserve()

    def test_invalid_nonce_rejected(self):
        for nonce in (None, "0" * 31, "g" * 32, "A" * 32):
            with self.subTest(nonce=nonce), self.assertRaisesRegex(ValueError, "INVALID_INCARNATION_NONCE"):
                store.prepared_record(SCOPE, NAME, DIGEST, SIG, nonce)

    def test_failure_after_publication_blocks_new_nonce(self):
        real_fsync = os.fsync
        count = [0]
        def fail_second(fd):
            count[0] += 1
            if count[0] == 2:
                raise OSError("injected after publication")
            return real_fsync(fd)
        with patch.object(store.os, "fsync", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "after publication"):
                self.reserve()
        self.assertEqual(len(list(self.directory.glob("v2-*.prepared.json"))), 1)
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_NAME_REQUIRES_RECONCILIATION"):
            self.reserve()

    def test_no_active_sender_integration(self):
        s = (SRC / "synology_scan_sync.py").read_text()
        self.assertNotIn("reserve_prepared", s)
        self.assertNotIn("incarnation_id", s)


if __name__ == "__main__":
    unittest.main()
