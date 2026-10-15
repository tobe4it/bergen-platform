"""Offline tests for manual same-subvolume archive rename; no NAS access."""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

CODE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(CODE))
import synology_same_volume_archive_move as move

PDF = b"%PDF-1.4\nsame-subvolume archive fixture\n%%EOF\n"
SHA = hashlib.sha256(PDF).hexdigest()
NAME = "Scan.pdf"
SCOPE = "Familie"


class SameVolumeArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="paperless-samevolume-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.folder = self.base / "Paperless"
        self.folder.mkdir(mode=0o700)
        self.state = self.base / "state"
        self.state.mkdir(mode=0o700)
        for path in (self.folder / ".paperless-archive",
                     self.state / "archive-move-journal"):
            path.mkdir(mode=0o700)
        lock = self.state / "sync.lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        self.source = self.folder / NAME
        self.source.write_bytes(PDF)
        self.source.chmod(0o600)
        stat_result = self.source.lstat()
        self.signature = move.source_signature(stat_result)
        self.rid = hashlib.sha256((SCOPE + "\0" + NAME).encode()).hexdigest()
        self.record = dict(
            status="SENT", scope=SCOPE, source=NAME,
            sha256=SHA, signature=self.signature,
            destination=SCOPE + "/Scan--nas-" + SHA + ".pdf",
        )
        receipt = self.state / (self.rid + ".json")
        receipt.write_text(json.dumps(self.record))
        receipt.chmod(0o600)
        self.proof = dict(
            schema_version=1, sender_receipt=receipt.name,
            bridge_receipt="a" * 24 + ".json",
            receiver_source=self.record["destination"], sha256=SHA,
            document_id=75,
        )
        self.target = (self.folder / ".paperless-archive" / "2026-10" /
                       (self.rid + ".pdf"))

    def execute(self, commit=False, proof=None, rename_callback=None):
        # Mock only the wall clock to simulate the 60s input-quiescence gate.
        # The rename itself is a real local filesystem operation in this suite.
        with patch.object(move.time, "time_ns",
                          return_value=time.time_ns() + 90_000_000_000):
            return move.archive_one(
                self.folder, self.state, SCOPE, NAME,
                proof if proof is not None else self.proof,
                commit=commit, archive_month="2026-10",
                rename_callback=rename_callback or self.rename_fixture)

    @staticmethod
    def rename_fixture(srcfd, old, dstfd, new):
        os.rename(old, new, src_dir_fd=srcfd, dst_dir_fd=dstfd)

    def event(self, stage):
        return self.state / "archive-move-journal" / (self.rid + "." + stage + ".json")

    def test_dry_run_makes_no_changes(self):
        before = self.source.read_bytes()
        result = self.execute()
        self.assertEqual(result["status"], "ARCHIVE_DRY_RUN")
        self.assertFalse(self.target.parent.exists())
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.event("prepared").exists())

    def test_move_is_same_inode_content_and_journalled(self):
        result = self.execute(commit=True)
        self.assertEqual(result["status"], "ARCHIVE_MOVED")
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.read_bytes(), PDF)
        self.assertEqual(self.target.stat().st_ino, self.signature[1])
        self.assertTrue(self.event("prepared").is_file())
        self.assertTrue(self.event("archived").is_file())
        journal = json.loads(self.event("archived").read_text())
        self.assertEqual(journal["document_id"], 75)
        self.assertEqual(journal["sha256"], SHA)
        self.assertTrue(journal["archived_at"].endswith("+00:00"))

    def test_kernel_rename_noreplace_refuses_existing_target(self):
        month = self.archive / "2026-10"
        month.mkdir(mode=0o700)
        target = month / "existing.pdf"
        target.write_bytes(b"existing target")
        sfd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
        dfd = os.open(month, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(OSError):
                move._noreplace_rename(sfd, NAME, dfd, "existing.pdf")
        finally:
            os.close(sfd)
            os.close(dfd)
        self.assertEqual(target.read_bytes(), b"existing target")
        self.assertEqual(self.source.read_bytes(), PDF)

    def test_kernel_rename_noreplace_moves_source_without_copy(self):
        month = self.archive / "2026-10"
        month.mkdir(mode=0o700)
        sfd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
        dfd = os.open(month, os.O_RDONLY | os.O_DIRECTORY)
        try:
            move._noreplace_rename(sfd, NAME, dfd, "moved.pdf")
        finally:
            os.close(sfd)
            os.close(dfd)
        self.assertFalse(self.source.exists())
        self.assertEqual((month / "moved.pdf").read_bytes(), PDF)
        self.assertEqual((month / "moved.pdf").stat().st_ino, self.signature[1])

    def test_no_automatic_purge_or_live_sender_wiring(self):
        program = (CODE / "synology_same_volume_archive_move.py").read_text()
        self.assertNotIn("os.unlink(", program)
        self.assertNotIn(".unlink(", program)
        self.assertNotIn("os.replace(", program)
        self.assertNotIn("shutil.move(", program)
        sender = (CODE / "synology_scan_sync.py").read_text()
        self.assertNotIn("synology_same_volume_archive_move", sender)

    def test_same_source_cannot_be_archived_twice(self):
        self.execute(commit=True)
        with self.assertRaises(FileNotFoundError):
            self.execute(commit=True)
        self.assertEqual(self.target.read_bytes(), PDF)

    def test_crash_before_rename_preserves_source_and_blocks_replay(self):
        def fail(*_):
            raise OSError("injected crash")
        with self.assertRaisesRegex(OSError, "injected crash"):
            self.execute(commit=True, rename_callback=fail)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.event("prepared").exists())
        self.assertFalse(self.event("archived").exists())
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_JOURNAL_ALREADY_EXISTS"):
            self.execute(commit=True)

    def test_crash_after_rename_preserves_archived_inode_and_requires_reconcile(self):
        def crash(src, old, dst, new):
            self.rename_fixture(src, old, dst, new)
            raise OSError("crash after rename")
        with self.assertRaisesRegex(OSError, "crash after rename"):
            self.execute(commit=True, rename_callback=crash)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.read_bytes(), PDF)
        self.assertTrue(self.event("prepared").exists())
        self.assertFalse(self.event("archived").exists())

    def test_destination_collision_before_journal_blocks(self):
        self.target.parent.mkdir(mode=0o700)
        self.target.write_bytes(b"do not replace")
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_TARGET_ALREADY_EXISTS"):
            self.execute(commit=True)
        self.assertEqual(self.target.read_bytes(), b"do not replace")
        self.assertTrue(self.source.exists())
        self.assertFalse(self.event("prepared").exists())

    def test_wrong_import_proof_blocks_without_writes(self):
        for proof in (
            dict(self.proof, sha256="f" * 64),
            dict(self.proof, document_id=True),
            dict(self.proof, bridge_receipt="../not-valid"),
            dict(self.proof, sender_receipt="x" * 64 + ".json"),
        ):
            with self.subTest(proof=proof), self.assertRaises(RuntimeError):
                self.execute(commit=True, proof=proof)
            self.assertTrue(self.source.exists())
            self.assertFalse(self.event("prepared").exists())

    def test_modified_source_refused_before_journal(self):
        self.source.write_bytes(PDF + b"tampered")
        with self.assertRaises(RuntimeError):
            self.execute(commit=True)
        self.assertFalse(self.event("prepared").exists())
        self.assertTrue(self.source.exists())

    def test_source_hardlink_refused(self):
        os.link(self.source, self.folder / "hardlink.pdf")
        with self.assertRaisesRegex(RuntimeError, "SOURCE_NOT_QUIESCENT_OR_UNSAFE"):
            self.execute(commit=True)

    def test_archive_symlink_refused(self):
        valid = self.folder / "valid-dir"
        self.target.parent.parent.rename(valid)
        (self.folder / ".paperless-archive").symlink_to(valid)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_ARCHIVE_DIRECTORY"):
            self.execute(commit=True)

    def test_archive_bad_permission_refused(self):
        (self.folder / ".paperless-archive").chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_ARCHIVE_DIRECTORY"):
            self.execute(commit=True)

    def test_unknown_month_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVE_MONTH"):
            with patch.object(move.time, "time_ns", return_value=time.time_ns() + 90_000_000_000):
                move.archive_one(self.folder, self.state, SCOPE, NAME, self.proof,
                                 archive_month="../BAD")

    def test_unapproved_filename_refused_before_reading(self):
        for filename in ("../another.pdf", ".hidden.pdf", "x/subdir.pdf", "bad.txt"):
            with self.subTest(filename=filename), self.assertRaisesRegex(
                    RuntimeError, "INVALID_ARCHIVE_SOURCE"):
                move.archive_one(self.folder, self.state, SCOPE,
                                 filename, self.proof)

    def test_archival_does_not_disable_30_day_retention(self):
        self.execute(commit=True)
        self.assertTrue(self.target.exists())
        self.assertNotIn("retention_worker", (CODE / "synology_scan_sync.py").read_text())


if __name__ == "__main__":
    unittest.main()
