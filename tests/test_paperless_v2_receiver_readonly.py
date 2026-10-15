"""Offline read-only staged receiver proof regression tests."""
import hashlib
import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ansible/files/paperless/verify_receiver_v2_staging.py"
spec = importlib.util.spec_from_file_location("v2_receiver_verify", MODULE)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

NAME = "nas-v2-" + "a" * 32 + "-" + "b" * 64 + ".pdf"
DATA = b"%PDF-1.4\n1 0 obj\n(test)\nendobj\n%%EOF\n"
DIGEST = hashlib.sha256(DATA).hexdigest()


class ReceiverAuditTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name) / "ingest-staging"
        self.root.mkdir(mode=0o750)
        self.root.chmod(0o750)
        (self.root / "Privat").mkdir(mode=0o750)
        (self.root / "Privat").chmod(0o750)
        for scope in ("Familie", "Eltern"):
            (self.root / scope).mkdir(mode=0o700)
            (self.root / scope).chmod(0o700)
        for scope in ("thomas", "nadja"):
            (self.root / "Privat" / scope).mkdir(mode=0o700)
            (self.root / "Privat" / scope).chmod(0o700)
        self.owner = os.geteuid()
        self.file = self.root / "Familie" / NAME
        self.file.write_bytes(DATA)
        self.file.chmod(0o600)

    def verify(self, scope="Familie", name=NAME, digest=DIGEST, size=len(DATA)):
        return v.verify(self.root, scope, name, digest, size,
                        root_uid=self.owner, ingest_uid=self.owner)

    def test_valid_pdf_hash_and_private_permissions(self):
        result = self.verify()
        self.assertEqual(result["receiver_sha256"], DIGEST)
        self.assertEqual(result["receiver_bytes"], len(DATA))
        self.assertTrue(result["verified_at_point_in_time"])
        self.assertFalse(result["new_file_confirmed"])
        self.assertFalse(result["paperless_import_confirmed"])
        self.assertFalse(result["source_delete_authorized"])

    def test_private_scope_valid(self):
        path = self.root / "Privat" / "thomas" / NAME
        path.write_bytes(DATA)
        path.chmod(0o600)
        self.assertEqual(self.verify(scope="Privat/thomas")["receiver_sha256"], DIGEST)

    def test_wrong_hash_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "RECEIVER_SHA256_MISMATCH"):
            self.verify(digest="0" * 64)

    def test_wrong_size_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_FILE"):
            self.verify(size=len(DATA) + 1)

    def test_corrupted_pdf_with_matching_expected_sha_is_rejected(self):
        bad = b"not actually a PDF"
        self.file.write_bytes(bad)
        with self.assertRaisesRegex(RuntimeError, "RECEIVER_PDF_INVALID"):
            self.verify(digest=hashlib.sha256(bad).hexdigest(), size=len(bad))

    def test_symlink_file_rejected(self):
        other = self.root / "Eltern" / "target.pdf"
        other.write_bytes(DATA)
        self.file.unlink()
        self.file.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_FILE"):
            self.verify()

    def test_hardlink_file_rejected(self):
        other = self.root / "Eltern" / "other.pdf"
        os.link(self.file, other)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_FILE"):
            self.verify()

    def test_public_permissions_rejected(self):
        self.file.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_FILE"):
            self.verify()

    def test_bad_parent_and_scope_modes_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_STAGING_ROOT"):
            self.verify()
        self.root.chmod(0o750)
        (self.root / "Familie").chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_DIRECTORY"):
            self.verify()

    def test_private_intermediate_directory_rejected(self):
        (self.root / "Privat").chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_DIRECTORY"):
            self.verify(scope="Privat/thomas")

    def test_symlinked_scope_directory_rejected(self):
        folder = self.root / "Familie"
        self.file.unlink()
        folder.rmdir()
        folder.symlink_to(self.root / "Eltern")
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_DIRECTORY"):
            self.verify()

    def test_wrong_user_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_RECEIVER_DIRECTORY"):
            v.verify(self.root, "Familie", NAME, DIGEST, len(DATA),
                     root_uid=self.owner, ingest_uid=self.owner + 1000)

    def test_bad_scope_and_filename_rejected(self):
        for scope, name in (
            ("Familie/../Eltern", NAME),
            ("Private/thomas", NAME),
            ("Familie", "../" + NAME),
            ("Familie", NAME[:-4] + ".txt"),
            ("Familie", "nas-v2-bad.pdf"),
            ("Familie", NAME + "/other"),
        ):
            with self.subTest(scope=scope, name=name):
                with self.assertRaisesRegex(ValueError, "INVALID_RECEIVER_EXPECTATIONS"):
                    self.verify(scope=scope, name=name)

    def test_invalid_expected_size_and_checksum_rejected(self):
        for size in (0, -1, True, v.MAX_BYTES + 1):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, "INVALID_RECEIVER_EXPECTATIONS"):
                    self.verify(size=size)
        with self.assertRaisesRegex(ValueError, "INVALID_RECEIVER_EXPECTATIONS"):
            self.verify(digest="not-a-digest")

    def test_stat_change_between_open_and_read_rejected(self):
        original = v.os.fstat
        count = [0]
        def changing(fd):
            value = original(fd)
            if stat.S_ISREG(value.st_mode):
                count[0] += 1
                if count[0] == 2:
                    # Simulates bytes changing while receiver is being read.
                    self.file.write_bytes(DATA + b"changed")
            return value
        with patch.object(v.os, "fstat", side_effect=changing):
            with self.assertRaisesRegex(RuntimeError, "RECEIVER_FILE_CHANGED_DURING_READ"):
                self.verify()

    def test_proxmox_playbook_requires_expected_guest_and_restricted_user(self):
        play = (ROOT / "ansible/playbooks/audit-paperless-v2-receiver.yml").read_text()
        self.assertIn("hosts: venombox", play)
        self.assertIn("'unprivileged: 1'", play)
        self.assertIn("paperless-ingest", play)
        self.assertIn("verify_receiver_v2_staging.py", play)
        self.assertIn("SENT_NOT_AUTHORIZED", play)
        self.assertIn("changed_when: false", play)
        self.assertNotIn("prepare-paperless-ingest-bridge.yml", play)
        self.assertNotIn("ansible.builtin.copy:", play)
        self.assertNotIn("ansible.builtin.file:", play)

    def test_no_mutations_or_sender_calls_in_script(self):
        src = MODULE.read_text(encoding="utf-8")
        for forbidden in ("os.unlink(", ".unlink(", "os.replace(", "os.rename(",
                          "os.chmod(", "os.chown(", "subprocess.", "shutil.",
                          ".write_bytes(", ".mkdir(", "rsync"):
            self.assertNotIn(forbidden, src)
        self.assertIn("NO_FILES_CHANGED", src)
        self.assertIn("SENT_NOT_AUTHORIZED", src)


if __name__ == "__main__":
    unittest.main()
