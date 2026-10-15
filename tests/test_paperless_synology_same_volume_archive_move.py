"""Offline tests for manual same-subvolume archive rename; no NAS access."""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        self.site = self.base / "paperless-scan"
        self.site.mkdir(mode=0o700)
        self.folder = self.site / "Paperless"
        self.folder.mkdir(mode=0o700)
        self.archive_root = self.site / move.PROTECTED_ARCHIVE_DIR
        self.archive_root.mkdir(mode=0o700)
        self.archive = self.archive_root / SCOPE
        self.archive.mkdir(mode=0o700)
        self.state = self.base / "state"
        self.state.mkdir(mode=0o700)
        (self.state / "archive-move-journal").mkdir(mode=0o700)
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
        self.target = self.archive / "2026-10" / (self.rid + ".pdf")

    def execute(self, commit=False, proof=None, rename_callback=None):
        # Mock only the wall clock to simulate the 60s input-quiescence gate.
        # The rename itself is a real local filesystem operation in this suite.
        with patch.object(move.time, "time_ns",
                          return_value=time.time_ns() + 90_000_000_000):
            return move.archive_one(
                self.folder, self.state, SCOPE, NAME,
                proof if proof is not None else self.proof,
                archive_scope_dir=self.archive,
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

    def test_full_archive_journal_flow_uses_kernel_noreplace(self):
        # Unlike earlier flow tests, exercise the real production rename
        # callback, not the test's plain os.rename substitute.
        with patch.object(move.time, "time_ns",
                          return_value=time.time_ns() + 90_000_000_000):
            result = move.archive_one(
                self.folder, self.state, SCOPE, NAME, self.proof,
                archive_scope_dir=self.archive,
                commit=True, archive_month="2026-10")
        self.assertEqual(result["status"], "ARCHIVE_MOVED")
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.read_bytes(), PDF)
        self.assertEqual(self.target.stat().st_ino, self.signature[1])
        self.assertTrue(self.event("prepared").is_file())
        self.assertTrue(self.event("archived").is_file())

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
        valid = self.archive_root / "valid-dir"
        self.archive.rename(valid)
        self.archive.symlink_to(valid)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_ARCHIVE_DIRECTORY"):
            self.execute(commit=True)

    def test_archive_bad_permission_refused(self):
        self.archive.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_ARCHIVE_DIRECTORY"):
            self.execute(commit=True)

    def test_unknown_month_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ARCHIVE_MONTH"):
            with patch.object(move.time, "time_ns", return_value=time.time_ns() + 90_000_000_000):
                move.archive_one(self.folder, self.state, SCOPE, NAME, self.proof,
                                 archive_scope_dir=self.archive,
                                 archive_month="../BAD")

    def test_unapproved_filename_refused_before_reading(self):
        for filename in ("../another.pdf", ".hidden.pdf", "x/subdir.pdf", "bad.txt"):
            with self.subTest(filename=filename), self.assertRaisesRegex(
                    RuntimeError, "INVALID_ARCHIVE_SOURCE"):
                move.archive_one(self.folder, self.state, SCOPE,
                                 filename, self.proof,
                                 archive_scope_dir=self.archive)

    def test_archiving_never_uses_obsolete_per_source_archive(self):
        old = self.folder / ".paperless-archive"
        old.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_NOT_IN_PROTECTED_SITE"):
            move.archive_one(
                self.folder, self.state, SCOPE, NAME, self.proof,
                archive_scope_dir=old)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.event("prepared").exists())

    def test_wrong_site_scope_cannot_share_another_scope_archive(self):
        wrong = self.archive_root / "Eltern"
        wrong.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_NOT_IN_PROTECTED_SITE"):
            move.archive_one(self.folder, self.state, SCOPE, NAME, self.proof,
                             archive_scope_dir=wrong)
        self.assertTrue(self.source.exists())

    def test_protected_archive_root_must_not_be_within_scan_source(self):
        nested = self.folder / move.PROTECTED_ARCHIVE_DIR / SCOPE
        nested.parent.mkdir(mode=0o700)
        nested.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_NOT_IN_PROTECTED_SITE"):
            move.archive_one(self.folder, self.state, SCOPE, NAME, self.proof,
                             archive_scope_dir=nested)

    def test_scope_to_site_contract(self):
        self.assertEqual(move.SITE_BY_SCOPE["Eltern"], "paperless-scan")
        self.assertEqual(move.SITE_BY_SCOPE["Familie"], "paperless-scan")
        self.assertEqual(move.SITE_BY_SCOPE["Privat/thomas"], "homes")
        self.assertEqual(move.SITE_BY_SCOPE["Privat/nadja"], "homes")
        self.assertNotIn('source_dir / ARCHIVE_DIR',
                         (CODE / "synology_same_volume_archive_move.py").read_text())

    def test_private_scope_path_requires_extra_protected_privat_layer(self):
        wanted = self.base / "homes" / move.PROTECTED_ARCHIVE_DIR / "Privat" / "thomas"
        move._validate_archive_scope_path(wanted, self.folder, "Privat/thomas")
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_NOT_IN_PROTECTED_SITE"):
            move._validate_archive_scope_path(wanted.parent, self.folder,
                                              "Privat/thomas")

    def test_main_resolves_site_root_by_device_boundary(self):
        original = Path.lstat

        def simulated_mount_info(path):
            st = original(path)
            if path == self.base:
                return SimpleNamespace(st_dev=st.st_dev + 101,
                                       st_mode=st.st_mode, st_uid=st.st_uid)
            if path == self.site:
                return SimpleNamespace(st_dev=st.st_dev,
                                       st_mode=st.st_mode, st_uid=0)
            return st

        with patch.object(Path, "lstat", simulated_mount_info):
            self.assertEqual(move._validated_protected_scope(
                self.folder, SCOPE, os.geteuid()), self.archive)

    def test_main_refuses_device_root_with_unexpected_name(self):
        original = Path.lstat

        def simulated_mount_info(path):
            st = original(path)
            if path == self.base:
                return SimpleNamespace(st_dev=st.st_dev + 101,
                                       st_mode=st.st_mode, st_uid=st.st_uid)
            if path == self.site:
                return SimpleNamespace(st_dev=st.st_dev,
                                       st_mode=st.st_mode, st_uid=0)
            return st

        with patch.object(Path, "lstat", simulated_mount_info):
            with self.assertRaisesRegex(RuntimeError, "ARCHIVE_SITE_ROOT_MISMATCH"):
                move._validated_protected_scope(
                    self.folder, "Privat/thomas", os.geteuid())

    def test_main_refuses_non_root_owned_site_boundary(self):
        original = Path.lstat

        def simulated_mount_info(path):
            st = original(path)
            if path == self.base:
                return SimpleNamespace(st_dev=st.st_dev + 101,
                                       st_mode=st.st_mode, st_uid=st.st_uid)
            return st

        with patch.object(Path, "lstat", simulated_mount_info):
            with self.assertRaisesRegex(RuntimeError, "ARCHIVE_SITE_ROOT_MISMATCH"):
                move._validated_protected_scope(self.folder, SCOPE, os.geteuid())

    def test_site_commit_gates_absent_by_default(self):
        for site in ("homes", "paperless-scan"):
            with self.subTest(site=site):
                with self.assertRaisesRegex(
                        RuntimeError, "ARCHIVE_SITE_GATE_NOT_APPROVED"):
                    move._require_site_commit_gate(self.base, site)

    def test_legacy_global_gate_never_activates_site(self):
        legacy = self.base / "archive-move.enabled"
        legacy.write_bytes(b"")
        legacy.chmod(0o600)
        with self.assertRaisesRegex(
                RuntimeError, "LEGACY_ARCHIVE_GATE_MUST_BE_ABSENT"):
            move._require_site_commit_gate(self.base, "paperless-scan")

    def test_symlink_or_wrong_mode_site_gate_is_rejected(self):
        gate = self.base / "archive-move.paperless-scan.enabled"
        gate.symlink_to(self.state / "sync.lock")
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_SITE_GATE_NOT_APPROVED"):
            move._require_site_commit_gate(self.base, "paperless-scan")
        gate.unlink()
        gate.write_bytes(b"")
        gate.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_SITE_GATE_NOT_APPROVED"):
            move._require_site_commit_gate(self.base, "paperless-scan")

    def test_gate_cannot_authorize_other_site(self):
        gate = self.base / "archive-move.homes.enabled"
        gate.write_bytes(b"")
        gate.chmod(0o600)
        original = Path.lstat

        def simulate_root_gate(path):
            st = original(path)
            if path == gate:
                return SimpleNamespace(st_mode=st.st_mode, st_uid=0,
                                       st_nlink=st.st_nlink)
            return st

        with patch.object(Path, "lstat", simulate_root_gate):
            move._require_site_commit_gate(self.base, "homes")
            with self.assertRaisesRegex(
                    RuntimeError, "ARCHIVE_SITE_GATE_NOT_APPROVED"):
                move._require_site_commit_gate(self.base, "paperless-scan")

    def test_disabled_worker_staging_rejects_both_site_gates(self):
        stage_yaml = (CODE.parent.parent / "playbooks" /
                      "stage-paperless-synology-archive-worker.yml").read_text()
        for gate in ("archive-move.enabled", "archive-move.homes.enabled",
                     "archive-move.paperless-scan.enabled"):
            self.assertIn(gate, stage_yaml)

    def test_archival_does_not_disable_30_day_retention(self):
        self.execute(commit=True)
        self.assertTrue(self.target.exists())
        self.assertNotIn("retention_worker", (CODE / "synology_scan_sync.py").read_text())


if __name__ == "__main__":
    unittest.main()
