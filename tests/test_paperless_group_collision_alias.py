"""Same-name group scan must never overwrite an immutable old v1 receipt."""
import hashlib
import importlib.util
import os
import stat
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CODE = (Path(__file__).resolve().parents[1] / "ansible/files/paperless")
SRC = CODE / "synology_group_collision_alias.py"
spec = importlib.util.spec_from_file_location("synology_group_collision_alias", SRC)
alias = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alias)


class CollisionAliasTests(unittest.TestCase):
    def test_different_scan_uuid_is_a_new_basename(self):
        x = alias.alias_basename("scan.pdf", "a" * 32)
        y = alias.alias_basename("scan.pdf", "b" * 32)
        self.assertNotEqual(x, y)
        self.assertTrue(x.startswith("scan--scan-"))
        self.assertTrue(x.endswith(".pdf"))

    def test_unicode_and_maximum_nas_basename_bytes(self):
        old = ("Überweisung" * 24) + ".pdf"
        value = alias.alias_basename(old, "f" * 32)
        self.assertLessEqual(len(value.encode("utf-8")), 255)
        self.assertTrue(value.endswith("--scan-" + "f" * 32 + ".pdf"))
        self.assertTrue(value.startswith("Überweisung"))

    def test_refuse_unsafe_source_and_bad_nonce(self):
        for n in ("../scan.pdf", ".private.pdf", "sub/scan.pdf",
                  "sub\\scan.pdf", "scan.txt", "scan\x00.pdf", ""):
            with self.subTest(n=n), self.assertRaises(ValueError):
                alias.alias_basename(n, "a" * 32)
        for token in ("z" * 32, "a" * 31, "", "A" * 32):
            with self.subTest(token=token), self.assertRaises(ValueError):
                alias.alias_basename("scan.pdf", token)

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base = Path(t.name)
        self.folder = self.base / "Familie"
        self.folder.mkdir()
        self.state = self.base / "private_state"
        self.state.mkdir(mode=0o700)
        self.pdf = self.folder / "scan.pdf"
        self.data = b"%PDF-1.4\nfresh group scan\n%%EOF\n"
        self.pdf.write_bytes(self.data)
        os.utime(self.pdf, (time.time() - 120, time.time() - 120))
        st = self.pdf.stat()
        self.original_sig = [st.st_dev, st.st_ino, st.st_size,
                             st.st_mtime_ns, st.st_ctime_ns]
        self.previous_sig = list(self.original_sig)
        self.previous_sig[1] += 20000
        self.old_receipt = dict(status="SENT", scope="Familie",
                                source="scan.pdf", sha256="b" * 64,
                                signature=self.previous_sig,
                                destination="Familie/old--nas-" + "b" * 64 + ".pdf")
        self.receipt_copy = dict(self.old_receipt)
        self.sync_stub = types.ModuleType("synology_scan_sync")
        self.sync_stub.SETTINGS = {"sync_user": __import__("pwd").getpwuid(os.geteuid()).pw_name}
        self.sync_stub.secure_state = lambda: None
        self.sync_stub.require_schedule_gate = lambda: None
        self.sync_stub.metadata = lambda path: path.lstat()
        self.sync_stub.signature = lambda s: [s.st_dev, s.st_ino, s.st_size,
                                               s.st_mtime_ns, s.st_ctime_ns]
        self.sync_stub.snapshot = self.make_snapshot
        self.sync_stub.receipt_path = lambda scope, name: self.state / (hashlib.sha256(name.encode()).hexdigest() + ".json")

    def make_snapshot(self, source, target):
        before = source.stat()
        data = source.read_bytes()
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest(), self.sync_stub.signature(before)

    def try_alias(self, old_receipt=None, rename=None):
        # Offline test mocks only the independent archive proof. Production
        # must fully verify all NAS archive events and archived PDF bytes.
        def test_rename(fd1, source, fd2, dest):
            if (self.folder / dest).exists():
                raise FileExistsError("COLLISION")
            os.rename(self.folder / source, self.folder / dest)
        with patch.dict(sys.modules, {"synology_scan_sync": self.sync_stub}):
            with patch.object(alias, "require_previous_archived",
                              return_value={"test_verified": True}):
                return alias.resolve_under_sender_lock(
                    self.folder, "Familie", self.pdf,
                    old_receipt if old_receipt is not None else self.old_receipt,
                    state=self.state, quiet_seconds=0,
                    rename=rename if rename is not None else test_rename,
                    nonce_factory=lambda: "c" * 32)

    def test_archived_old_name_creates_new_alias_not_new_old_receipt(self):
        changed = self.try_alias()
        self.assertIsNotNone(changed)
        self.assertFalse(self.pdf.exists())
        self.assertEqual(changed.read_bytes(), self.data)
        self.assertEqual(self.receipt_copy, self.old_receipt)
        self.assertTrue(changed.name.endswith("--scan-" + "c" * 32 + ".pdf"))
        self.assertFalse(self.sync_stub.receipt_path("Familie", changed.name).exists())

    def test_alias_must_be_empty_and_source_not_overwritten(self):
        target = self.folder / alias.alias_basename(self.pdf.name, "c" * 32)
        target.write_bytes(b"existing scan")
        with self.assertRaises(FileExistsError):
            self.try_alias()
        self.assertEqual(self.pdf.read_bytes(), self.data)
        self.assertEqual(target.read_bytes(), b"existing scan")

    def test_same_inode_metadata_only_change_stops(self):
        old = dict(self.old_receipt, signature=list(self.original_sig))
        old["signature"][4] -= 1
        with self.assertRaisesRegex(RuntimeError, "OLD_INODE_STILL_ACTIVE"):
            self.try_alias(old)
        self.assertTrue(self.pdf.exists())

    def test_archival_proof_is_mandatory(self):
        with patch.dict(sys.modules, {"synology_scan_sync": self.sync_stub}):
            with patch.object(alias, "require_previous_archived",
                              side_effect=RuntimeError("NOT_ARCHIVED")):
                with self.assertRaisesRegex(RuntimeError, "NOT_ARCHIVED"):
                    alias.resolve_under_sender_lock(
                        self.folder, "Familie", self.pdf,
                        self.old_receipt, state=self.state,
                        quiet_seconds=0, nonce_factory=lambda: "f" * 32)
        self.assertEqual(self.pdf.read_bytes(), self.data)

    def test_private_scope_never_renamed(self):
        with self.assertRaisesRegex(RuntimeError, "GROUP_COLLISION_SCOPE_OR_USER_INVALID"):
            self.try_private_alias()
        self.assertTrue(self.pdf.exists())

    def try_private_alias(self):
        with patch.dict(sys.modules, {"synology_scan_sync": self.sync_stub}):
            return alias.resolve_under_sender_lock(
                self.folder, "Privat/thomas", self.pdf,
                self.old_receipt, state=self.state, quiet_seconds=0)

    def test_sender_requires_gate_and_group_scope_and_no_v2_replacement(self):
        sender = (CODE / "synology_scan_sync.py").read_text(encoding="utf-8")
        self.assertIn("synology_group_collision_alias", sender)
        self.assertIn('scope in ("Familie", "Eltern")', sender)
        self.assertIn("commit and scheduled and only is None", sender)
        self.assertIn("UNREVIEWED_COLLISION_HELPER", sender)
        self.assertIn("receipt_file = receipt_path(scope, path.name)", sender)
        self.assertIn("read_receipt(receipt_file)", sender)
        self.assertIn("synology_group_collision_alias.py", sender)
        self.assertNotIn("attempted_record", sender)


if __name__ == "__main__":
    unittest.main()
