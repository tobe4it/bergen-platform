"""Safety tests for strictly /tmp-contained Paperless quarantine lifecycle.

No home directories, DSM files, Paperless documents or real NAS are touched.
"""
import hashlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(SRC))
import synology_receipt_v2_store as store
import v2_quarantine_fixture_only as fixture

PDF = b"%PDF-1.4\nprivate fixture, never a real scan\n%%EOF\n"
SHA = hashlib.sha256(PDF).hexdigest()
SCOPE = "Privat/thomas"
NAME = "Scan.pdf"


class QuarantineFixtureTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(
            prefix="bergen-paperless-archive-fixture-", dir="/tmp")
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.root.chmod(0o700)
        for top in ("sources", "quarantine", "state"):
            folder = self.root / top
            folder.mkdir(mode=0o700)
            folder.chmod(0o700)
        for top in ("sources", "quarantine"):
            private = self.root / top / "Privat"
            private.mkdir(mode=0o700)
            private.chmod(0o700)
            scoped = private / "thomas"
            scoped.mkdir(mode=0o700)
            scoped.chmod(0o700)
        lock = self.root / "state" / "sync.lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        self.source = self.root / "sources" / SCOPE / NAME
        self.source.write_bytes(PDF)
        self.source.chmod(0o600)
        st = self.source.lstat()
        sig = [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
        prepared = store.prepared_record(SCOPE, NAME, SHA, sig, "a" * 32)
        self.sent = store.sent_record(prepared, {
            "receiver_source": prepared["destination"],
            "receiver_sha256": SHA, "new_file_confirmed": True,
        })
        self.imported = {
            "schema_version": 2, "status": "IMPORTED",
            "bridge_receipt": "b" * 24 + ".json",
            "receiver_source": prepared["destination"],
            "receipt_id": prepared["receipt_id"],
            "sha256": SHA,
            "document_id": 78,
        }
        self.target = (self.root / "quarantine" / SCOPE /
                       (prepared["receipt_id"] + ".pdf"))

    def archive(self):
        return fixture.archive_fixture(self.root, self.sent, self.imported)

    def delete(self, tested=True):
        return fixture.delete_fixture_original(
            self.root, self.sent, self.imported,
            offline_restore_test_confirmed=tested)

    def restore(self):
        return fixture.restore_fixture_original(self.root, self.sent, self.imported)

    def journal(self, stage):
        return (self.root / "state" /
                (self.sent["receipt_id"] + "." + stage.lower() + ".json"))

    def test_copy_preserves_original_and_checks_digest(self):
        result = self.archive()
        self.assertTrue(result["quarantine_copy_verified"])
        self.assertTrue(self.source.is_file())
        self.assertEqual(self.source.read_bytes(), PDF)
        self.assertEqual(self.target.read_bytes(), PDF)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertTrue(self.journal("QUARANTINE_PREPARED").is_file())
        self.assertTrue(self.journal("ARCHIVED").is_file())
        self.assertFalse(self.journal("SOURCE_REMOVE_INTENT").exists())
        self.assertFalse(result["production_approved"])

    def test_copy_never_uses_cross_subvolume_rename(self):
        body = (SRC / "v2_quarantine_fixture_only.py").read_text()
        for forbidden in ("os.replace(", "os.rename(", "shutil.move(", "rename("):
            self.assertNotIn(forbidden, body)
        self.assertIn("os.link(temp, destination", body)

    def test_delete_requires_explicit_offline_restore_test_ack(self):
        self.archive()
        with self.assertRaisesRegex(RuntimeError, "RESTORE_TEST_REQUIRED"):
            self.delete(tested=False)
        self.assertEqual(self.source.read_bytes(), PDF)
        self.assertFalse(self.journal("SOURCE_REMOVE_INTENT").exists())

    def test_delete_and_create_only_restore_roundtrip(self):
        self.archive()
        result = self.delete()
        self.assertTrue(result["fixture_source_removed"])
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.read_bytes(), PDF)
        for stage in ("SOURCE_REMOVE_INTENT", "SOURCE_REMOVED"):
            self.assertTrue(self.journal(stage).is_file())
        restored = self.restore()
        self.assertTrue(restored["fixture_restored"])
        self.assertEqual(self.source.read_bytes(), PDF)
        self.assertTrue(self.journal("RESTORED").exists())
        with self.assertRaisesRegex(RuntimeError, "FIXTURE_RESTORE_ALREADY_RECORDED"):
            self.restore()

    def test_deleting_original_cannot_be_repeated(self):
        self.archive()
        self.delete()
        with self.assertRaisesRegex(RuntimeError, "SOURCE_REMOVAL_ALREADY_ATTEMPTED"):
            self.delete()
        self.assertEqual(self.target.read_bytes(), PDF)

    def test_delete_without_archive_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            self.delete()
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_changed_source_after_archive_blocks_delete(self):
        self.archive()
        self.source.write_bytes(PDF + b"tamper")
        with self.assertRaises(RuntimeError):
            self.delete()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.journal("SOURCE_REMOVE_INTENT").exists())

    def test_replaced_source_same_digest_blocks_delete(self):
        self.archive()
        self.source.unlink()
        self.source.write_bytes(PDF)
        self.source.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "ORIGINAL_INCARNATION_CHANGED"):
            self.delete()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.target.read_bytes(), PDF)

    def test_tampered_archive_blocks_delete(self):
        self.archive()
        self.target.write_bytes(PDF + b"tamper")
        with self.assertRaises(RuntimeError):
            self.delete()
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_missing_archive_blocks_delete(self):
        self.archive()
        self.target.unlink()
        with self.assertRaises(FileNotFoundError):
            self.delete()
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_tampered_archive_journal_blocks_delete(self):
        self.archive()
        self.journal("ARCHIVED").write_bytes(b"garbage")
        with self.assertRaisesRegex(RuntimeError, "FIXTURE_JOURNAL_CHANGED"):
            self.delete()
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_copy_crash_keeps_source_and_blocks_retry(self):
        def fail(*args):
            raise OSError("injected archive IO failure")
        with patch.object(fixture, "_copy_private", side_effect=fail):
            with self.assertRaisesRegex(OSError, "injected archive"):
                self.archive()
        self.assertTrue(self.source.is_file())
        self.assertTrue(self.journal("QUARANTINE_PREPARED").exists())
        self.assertFalse(self.journal("ARCHIVED").exists())
        with self.assertRaisesRegex(RuntimeError, "UNRESOLVED_QUARANTINE"):
            self.archive()

    def test_refuse_existing_archive_destination_without_journal(self):
        self.target.write_bytes(PDF)
        self.target.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_DESTINATION_ALREADY_EXISTS"):
            self.archive()
        self.assertFalse(self.journal("QUARANTINE_PREPARED").exists())

    def test_refuse_source_symlink_before_journal(self):
        original = self.root / "other.pdf"
        self.source.rename(original)
        self.source.symlink_to(original)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CHANGED_OFFLINE_PDF"):
            self.archive()
        self.assertFalse(self.journal("QUARANTINE_PREPARED").exists())

    def test_refuse_source_hardlink_before_journal(self):
        os.link(self.source, self.root / "other.pdf")
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CHANGED_OFFLINE_PDF"):
            self.archive()

    def test_refuse_world_readable_original(self):
        self.source.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OR_CHANGED_OFFLINE_PDF"):
            self.archive()

    def test_source_scope_directory_symlink_is_rejected(self):
        scoped = self.root / "sources" / SCOPE
        self.source.unlink()
        scoped.rmdir()
        scoped.symlink_to(self.root / "quarantine" / SCOPE)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_OFFLINE_DIRECTORY"):
            self.archive()

    def test_refuse_root_outside_exact_tmp_fixture_namespace(self):
        with self.assertRaisesRegex(ValueError, "OFFLINE_FIXTURE_ROOT_REQUIRED"):
            fixture.archive_fixture(Path("/volume1"), self.sent, self.imported)
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_wrong_import_receipt_id_blocks_archival(self):
        fake = dict(self.imported, receipt_id="v2-" + "f" * 32 + "-" + "a" * 64)
        with self.assertRaisesRegex(RuntimeError, "V2_IMPORT_IDENTITY_MISMATCH"):
            fixture.archive_fixture(self.root, self.sent, fake)
        self.assertFalse(self.journal("QUARANTINE_PREPARED").exists())

    def test_wrong_scoped_pdf_digest_blocks_archival(self):
        self.source.write_bytes(PDF + b"changed")
        with self.assertRaises(RuntimeError):
            self.archive()
        self.assertFalse(self.journal("QUARANTINE_PREPARED").exists())

    def test_recovery_requires_all_four_immutable_journal_events(self):
        self.archive()
        self.delete()
        self.journal("SOURCE_REMOVE_INTENT").unlink()
        with self.assertRaises(FileNotFoundError):
            self.restore()
        self.assertFalse(self.source.exists())
        self.assertTrue(self.target.exists())

    def test_no_live_entrypoint_or_prod_sender_integration(self):
        code = (SRC / "v2_quarantine_fixture_only.py").read_text()
        self.assertNotIn('if __name__ == "__main__"', code)
        self.assertNotIn('if __name__ == \'__main__\'', code)
        self.assertIn("OFFLINE FIXTURE ONLY", code)
        self.assertIn('root.parent != Path("/tmp")', code)
        active = (SRC / "synology_scan_sync.py").read_text()
        self.assertNotIn("v2_quarantine_fixture_only", active)


if __name__ == "__main__":
    unittest.main()
