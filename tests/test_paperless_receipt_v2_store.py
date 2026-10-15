"""Offline append-only NAS v2 journal tests; only temporary directories are written."""
import copy
import hashlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SOURCE))
import synology_receipt_v2_store as store

SHA = hashlib.sha256(b"%PDF-1.4 offline %%EOF").hexdigest()
SIG = [47, 200, 90, 120, 130]
NONCE = "a" * 32


class AppendOnlyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.directory.chmod(0o700)
        self.lock = self.directory / "sync.lock"
        self.lock.write_bytes(b"")
        self.lock.chmod(0o600)
        self.prepared = store.prepared_record("Privat/thomas", "Gescanntes Dokument.pdf",
                                               SHA, SIG, NONCE)
        self.sent = store.sent_record(self.prepared, {
            "receiver_source": self.prepared["destination"],
            "receiver_sha256": SHA,
            "new_file_confirmed": True,
        })
        self.prepared_path = self.directory / (self.prepared["receipt_id"] + ".prepared.json")
        self.sent_path = self.directory / (self.prepared["receipt_id"] + ".sent.json")

    def publish_prepared(self):
        return store.publish_event(self.directory, self.prepared)

    def test_prepared_is_canonical_private_and_immutable(self):
        self.assertEqual(store.publish_event(self.directory, self.prepared),
                         (self.prepared_path, True))
        self.assertEqual(self.prepared_path.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(self.prepared_path.stat().st_mode), 0o600)
        self.assertEqual(self.prepared_path.read_bytes(), store._canonical(self.prepared))
        self.assertEqual([x.name for x in self.directory.iterdir() if x.name != "sync.lock"],
                         [self.prepared_path.name])

    def test_prepared_retry_is_idempotent(self):
        self.publish_prepared()
        self.assertEqual(self.publish_prepared(), (self.prepared_path, False))

    def test_sent_requires_durable_matching_prepared(self):
        with self.assertRaises(FileNotFoundError):
            store.publish_event(self.directory, self.sent)
        self.assertFalse(self.sent_path.exists())
        self.publish_prepared()
        self.assertEqual(store.publish_event(self.directory, self.sent), (self.sent_path, True))
        self.assertEqual(store.publish_event(self.directory, self.sent), (self.sent_path, False))
        self.assertEqual(self.prepared_path.read_bytes(), store._canonical(self.prepared))
        self.assertEqual(self.sent_path.read_bytes(), store._canonical(self.sent))

    def test_altered_prepared_event_blocks_sent(self):
        self.publish_prepared()
        tampered = self.prepared_path.read_bytes().replace(b"PREPARED", b"PREPAREX")
        self.prepared_path.write_bytes(tampered)
        with self.assertRaisesRegex(RuntimeError, "MISSING_OR_MISMATCHED_PREPARED"):
            store.publish_event(self.directory, self.sent)
        self.assertFalse(self.sent_path.exists())

    def test_prepared_conflict_same_id_new_nonce_fails_closed(self):
        self.publish_prepared()
        conflict = copy.deepcopy(self.prepared)
        conflict["incarnation_nonce"] = "b" * 32
        with self.assertRaisesRegex(ValueError, "EVENT_ID_OR_DESTINATION_MISMATCH"):
            store.publish_event(self.directory, conflict)
        self.assertEqual(self.prepared_path.read_bytes(), store._canonical(self.prepared))

    def test_existing_symlink_is_never_followed(self):
        other = self.directory / "other"
        other.write_bytes(b"private data")
        self.prepared_path.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_FILE"):
            self.publish_prepared()
        self.assertEqual(other.read_bytes(), b"private data")

    def test_existing_hardlink_and_world_readable_rejected(self):
        for kind in ("hardlink", "world"):
            with self.subTest(kind=kind):
                self.prepared_path.unlink(missing_ok=True)
                if kind == "hardlink":
                    other = self.directory / "other"
                    other.write_bytes(store._canonical(self.prepared))
                    other.chmod(0o600)
                    os.link(other, self.prepared_path)
                else:
                    self.prepared_path.write_bytes(store._canonical(self.prepared))
                    self.prepared_path.chmod(0o644)
                with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_FILE"):
                    self.publish_prepared()
                self.prepared_path.unlink()

    def test_unsafe_directory_and_lock_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
            self.publish_prepared()
        self.directory.chmod(0o700)
        self.lock.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_SYNC_LOCK"):
            self.publish_prepared()
        self.assertFalse(self.prepared_path.exists())

    def test_existing_sender_lock_blocks_concurrent_publication(self):
        from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
        fd = os.open(self.lock, os.O_RDONLY)
        try:
            flock(fd, LOCK_EX | LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.publish_prepared()
            self.assertFalse(self.prepared_path.exists())
        finally:
            flock(fd, LOCK_UN)
            os.close(fd)

    def test_preexisting_v1_receipt_is_not_modified(self):
        legacy = self.directory / ("f" * 64 + ".json")
        legacy.write_bytes(b'{"status": "SENT"}')
        legacy.chmod(0o600)
        before = legacy.read_bytes()
        self.publish_prepared()
        self.assertEqual(legacy.read_bytes(), before)
        self.assertTrue(legacy.exists())

    def test_failed_write_before_publish_does_not_create_event(self):
        real_fsync = os.fsync
        first = [True]
        def fail_file_sync(fd):
            if first[0]:
                first[0] = False
                raise OSError("injected before publish")
            return real_fsync(fd)
        with patch.object(store.os, "fsync", side_effect=fail_file_sync):
            with self.assertRaisesRegex(OSError, "before publish"):
                self.publish_prepared()
        self.assertFalse(self.prepared_path.exists())
        self.assertFalse(any(p.name.startswith(".v2-receipt-") for p in self.directory.iterdir()))

    def test_post_publish_fsync_failure_keeps_event_and_retry_recovers(self):
        real_fsync = os.fsync
        n = [0]
        def fail_dir_sync(fd):
            n[0] += 1
            if n[0] == 2:
                raise OSError("injected after publish")
            return real_fsync(fd)
        with patch.object(store.os, "fsync", side_effect=fail_dir_sync):
            with self.assertRaisesRegex(OSError, "after publish"):
                self.publish_prepared()
        self.assertEqual(self.prepared_path.read_bytes(), store._canonical(self.prepared))
        self.assertEqual(self.publish_prepared(), (self.prepared_path, False))

    def test_orphan_temp_is_not_removed(self):
        orphan = self.directory / ".v2-receipt-older.tmp"
        orphan.write_bytes(b"retained for review")
        self.publish_prepared()
        self.assertEqual(orphan.read_bytes(), b"retained for review")

    def test_reject_fake_evidence_and_invalid_nonce(self):
        bad = dict(self.prepared, incarnation_nonce="bad")
        with self.assertRaisesRegex(ValueError, "INVALID_INCARNATION_NONCE"):
            store.publish_event(self.directory, bad)
        with self.assertRaisesRegex(ValueError, "TRANSFER_EVIDENCE_MISMATCH"):
            store.sent_record(self.prepared, dict(self.sent["transfer_evidence"],
                                                   new_file_confirmed=False))
        with self.assertRaisesRegex(ValueError, "TRANSFER_EVIDENCE_MISMATCH"):
            store.sent_record(self.prepared, dict(self.sent["transfer_evidence"],
                                                   receiver_sha256="f" * 64))

    def test_nonexistent_directory_not_created(self):
        missing = self.directory / "does-not-exist"
        with self.assertRaises(FileNotFoundError):
            store.publish_event(missing, self.prepared)
        self.assertFalse(missing.exists())

    def test_integer_v2_schema_compatibility(self):
        from synology_receipt_versions import classify_existing
        args = ("Privat/thomas", "Gescanntes Dokument.pdf", SHA, SIG)
        self.assertEqual(classify_existing([], *args, version=2), "NEW_VERSION_READY")
        self.assertEqual(classify_existing([], *args, version="v2"), "NEW_VERSION_READY")
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_RECEIPT_VERSION"):
            classify_existing([], *args, version=True)

    def test_no_production_entrypoint_or_live_paths(self):
        s = (SOURCE / "synology_receipt_v2_store.py").read_text(encoding="utf-8")
        self.assertIn("OFFLINE ONLY", s)
        self.assertNotIn('if __name__ == "__main__"', s)
        self.assertNotIn("/volume1", s)
        self.assertNotIn("os.replace(", s)
        self.assertNotIn("subprocess.", s)
        active = (SOURCE / "synology_scan_sync.py").read_text(encoding="utf-8")
        self.assertNotIn("import synology_receipt_v2_store", active)


if __name__ == "__main__":
    unittest.main()
