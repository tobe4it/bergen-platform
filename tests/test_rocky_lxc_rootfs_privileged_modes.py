#!/usr/bin/env python3
"""Synthetic, no-I/O checks for Rocky rootfs SUID/SGID diagnostic."""
import importlib.util
from pathlib import Path
import sys
import tarfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "ansible/files/nextcloud"
sys.path.insert(0, str(SOURCE))
spec = importlib.util.spec_from_file_location(
    "rocky_mode_audit", SOURCE / "audit_rocky_lxc_rootfs_privileged_modes.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def member(path="usr/bin/example", mode=0o4755, uid=0, gid=0,
           kind=tarfile.REGTYPE):
    m = tarfile.TarInfo(path)
    m.type = kind
    m.mode = mode
    m.uid = uid
    m.gid = gid
    return m


class PrivilegedModeTests(unittest.TestCase):
    def test_suid_file_shows_numeric_mode_and_owner(self):
        result = audit.privileged_regular_record(member())
        self.assertEqual(result["path"], "usr/bin/example")
        self.assertEqual(result["mode"], "4755")
        self.assertEqual(result["uid"], 0)
        self.assertTrue(result["setuid"])
        self.assertFalse(result["setgid"])

    def test_sgid_regular_file_accepted(self):
        result = audit.privileged_regular_record(member(mode=0o2750))
        self.assertEqual(result["mode"], "2750")
        self.assertFalse(result["setuid"])
        self.assertTrue(result["setgid"])

    def test_combined_bits_and_world_writable_reported(self):
        result = audit.privileged_regular_record(member(mode=0o6777))
        self.assertTrue(result["world_writable"])
        self.assertTrue(result["setuid"])
        self.assertTrue(result["setgid"])

    def test_ordinary_file_ignored(self):
        self.assertIsNone(audit.privileged_regular_record(member(mode=0o755)))

    def test_symlink_is_not_treated_as_privileged_regular(self):
        self.assertIsNone(audit.privileged_regular_record(
            member(mode=0o4755, kind=tarfile.SYMTYPE)))

    def test_traversal_rejected(self):
        with self.assertRaisesRegex(audit.rootfs.AuditBlocked, "UNSAFE_MEMBER_SEGMENT"):
            audit.privileged_regular_record(member(path="../../wrong"))

    def test_uid_gid_invalid_rejected(self):
        with self.assertRaisesRegex(audit.rootfs.AuditBlocked, "INVALID_PRIVILEGED_OWNER"):
            audit.privileged_regular_record(member(uid=-1))

    def test_unexpected_mode_bits_rejected(self):
        with self.assertRaisesRegex(audit.rootfs.AuditBlocked, "INVALID_PRIVILEGED_MODE"):
            audit.privileged_regular_record(member(mode=0o14755))


if __name__ == "__main__":
    unittest.main()
