"""Offline-only atomic persistence and crash/retry tests for v2 decisions."""
import copy
import importlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SRC_DIR))
import deleted_by_user_decision_journal as journal
import deleted_by_user_decision_store as store
import synology_receipt_versions as versions

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


class DeletedByUserStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        os.chmod(self.directory, 0o700)
        self.record = journal.build(NAS, DELETED)
        self.target = self.directory / (self.record["event_id"] + ".json")

    def test_atomic_create(self):
        path, created = store.publish_once(self.directory, self.record)
        self.assertEqual(path, self.target)
        self.assertTrue(created)
        self.assertEqual(path.read_bytes(), journal.canonical(self.record))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(list(self.directory.iterdir()), [path])

    def test_idempotent_retry(self):
        first = store.publish_once(self.directory, self.record)
        second = store.publish_once(self.directory, self.record)
        self.assertEqual(first, (self.target, True))
        self.assertEqual(second, (self.target, False))
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_conflicting_bytes_not_overwritten(self):
        store.publish_once(self.directory, self.record)
        self.target.write_bytes(b"x" * len(journal.canonical(self.record)))
        with self.assertRaisesRegex(RuntimeError, "CONFLICTING_JOURNAL_RECORD"):
            store.publish_once(self.directory, self.record)
        self.assertEqual(self.target.read_bytes(), b"x" * len(journal.canonical(self.record)))

    def test_existing_symlink_not_followed(self):
        other = self.directory / "other"
        other.write_bytes(b"protected")
        self.target.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            store.publish_once(self.directory, self.record)
        self.assertEqual(other.read_bytes(), b"protected")

    def test_existing_hardlink_not_followed(self):
        other = self.directory / "other"
        other.write_bytes(journal.canonical(self.record))
        os.link(other, self.target)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            store.publish_once(self.directory, self.record)
        self.assertEqual(other.read_bytes(), journal.canonical(self.record))

    def test_existing_world_readable_file_rejected(self):
        self.target.write_bytes(journal.canonical(self.record))
        self.target.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CONFLICTING"):
            store.publish_once(self.directory, self.record)

    def test_unsafe_directory_mode_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
            store.publish_once(self.directory, self.record)
        self.assertFalse(self.target.exists())

    def test_relative_directory_rejected(self):
        with self.assertRaisesRegex(ValueError, "ABSOLUTE_PRIVATE"):
            store.publish_once(Path("relative"), self.record)

    def test_symlink_directory_rejected(self):
        alias = self.directory.parent / (self.directory.name + "-alias")
        alias.symlink_to(self.directory, target_is_directory=True)
        self.addCleanup(alias.unlink)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_JOURNAL_DIRECTORY"):
            store.publish_once(alias, self.record)

    def test_missing_directory_not_created(self):
        missing = self.directory / "nonexistent"
        with self.assertRaises(FileNotFoundError):
            store.publish_once(missing, self.record)
        self.assertFalse(missing.exists())

    def test_invalid_record_does_not_touch_directory(self):
        invalid = copy.deepcopy(self.record)
        invalid["event"] = "IMPORTED"
        with self.assertRaisesRegex(ValueError, "INVALID_USER_DELETION_JOURNAL_FIELDS"):
            store.publish_once(self.directory, invalid)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_crash_before_publish_no_partial_record(self):
        original = os.fsync
        count = [0]
        def fail_first(fd):
            count[0] += 1
            if count[0] == 1:
                raise OSError("simulated fsync before publication")
            return original(fd)
        with patch.object(store.os, "fsync", side_effect=fail_first):
            with self.assertRaisesRegex(OSError, "before publication"):
                store.publish_once(self.directory, self.record)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertTrue(store.publish_once(self.directory, self.record)[1])

    def test_crash_after_publish_retry_recovers(self):
        original = os.fsync
        count = [0]
        def fail_second(fd):
            count[0] += 1
            if count[0] == 2:
                raise OSError("simulated fsync after publication")
            return original(fd)
        with patch.object(store.os, "fsync", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "after publication"):
                store.publish_once(self.directory, self.record)
        self.assertEqual(self.target.read_bytes(), journal.canonical(self.record))
        self.assertEqual(store.publish_once(self.directory, self.record), (self.target, False))

    def test_orphan_temp_never_reused_or_removed(self):
        orphan = self.directory / ".deleted-by-user-prior-crash.tmp"
        orphan.write_bytes(b"untrusted orphan")
        path, created = store.publish_once(self.directory, self.record)
        self.assertTrue(created)
        self.assertEqual(orphan.read_bytes(), b"untrusted orphan")
        self.assertEqual(path.read_bytes(), journal.canonical(self.record))

    def test_new_same_name_incarnation_remains_blocked(self):
        old = {
            "scope": journal.SCOPE, "source": journal.SOURCE,
            "status": "SENT", "sha256": DIGEST,
            "signature": [47, 100, 1024, 1, 1],
        }
        decision = versions.classify_existing(
            [old], journal.SCOPE, journal.SOURCE, "b" * 64,
            [47, 101, 2048, 2, 2], version=2
        )
        self.assertEqual(decision, "BLOCK_NAME_REUSE_PENDING_ARCHIVE_PROOF")

    def test_no_production_entrypoint_or_default_path(self):
        src = (SRC_DIR / "deleted_by_user_decision_store.py").read_text()
        self.assertNotIn('if __name__ == "__main__"', src)
        self.assertNotIn("/volume1", src)
        self.assertNotIn("/srv/bergen-paperless", src)
        self.assertNotIn("os.replace(", src)
        self.assertNotIn("shutil.rmtree(", src)
        self.assertEqual(src.count("os.unlink("), 1)
        self.assertIn("os.unlink(temporary)", src)


if __name__ == "__main__":
    unittest.main()
