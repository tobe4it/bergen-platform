#!/usr/bin/env python3
"""Synthetic xz-tar tests for the networkless Rocky 9.8 structural audit."""
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest


SOURCE = (Path(__file__).resolve().parents[1]
          / "ansible/files/nextcloud/audit_rocky_lxc_rootfs.py")
spec = importlib.util.spec_from_file_location("rocky_lxc_audit", SOURCE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def make_archive(extra=(), release="Rocky Linux release 9.8 (Blue Onyx)\n"):
    data = io.BytesIO()
    with tarfile.open(mode="w:xz", fileobj=data) as tar:
        def add(name, content=b"", kind=tarfile.REGTYPE, link=""):
            info = tarfile.TarInfo(name=name)
            info.type = kind
            info.linkname = link
            info.mode = 0o644
            info.size = len(content) if kind == tarfile.REGTYPE else 0
            tar.addfile(info, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
        for index in range(110):
            add("dir%03d" % index, kind=tarfile.DIRTYPE)
        for index in range(1100):
            add("dir000/file%04d" % index, b"x")
        add("etc/rocky-release", release.encode())
        add("usr/lib/os-release", b'ID="rocky"\nVERSION_ID="9.8"\n')
        add("etc/os-release", kind=tarfile.SYMTYPE, link="../usr/lib/os-release")
        for item in extra:
            add(**item)
    data.seek(0)
    return data


class RockyLxcAuditTests(unittest.TestCase):
    def test_valid_signed_archive_shape(self):
        result = audit.inspect_archive(make_archive())
        self.assertEqual(result["result"], "ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS")
        self.assertEqual(result["rocky_version"], "9.8")
        self.assertEqual(result["symlink_count"], 1)
        self.assertFalse(result["archive_extracted"])

    def test_path_traversal_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "UNSAFE_MEMBER_SEGMENT"):
            audit.inspect_archive(make_archive([{"name": "../escape", "content": b"x"}]))

    def test_absolute_link_inside_virtual_root_accepted(self):
        result = audit.inspect_archive(make_archive([{
            "name": "var/test-link", "kind": tarfile.SYMTYPE,
            "link": "/usr/lib/os-release",
        }]))
        self.assertEqual(result["absolute_symlink_count"], 1)

    def test_dangling_absolute_link_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "DANGLING_SYMLINK"):
            audit.inspect_archive(make_archive([{
                "name": "var/test-link", "kind": tarfile.SYMTYPE,
                "link": "/nonexistent/target",
            }]))

    def test_absolute_link_escape_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "SYMLINK_ESCAPES_ROOT"):
            audit.inspect_archive(make_archive([{
                "name": "var/test-link", "kind": tarfile.SYMTYPE,
                "link": "/../../etc/passwd",
            }]))

    def test_link_escape_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "SYMLINK_ESCAPES_ROOT"):
            audit.inspect_archive(make_archive([{
                "name": "var/test-link", "kind": tarfile.SYMTYPE, "link": "../../../etc/passwd",
            }]))

    def test_hardlink_to_earlier_regular_accepted(self):
        result = audit.inspect_archive(make_archive([{
            "name": "test-link", "kind": tarfile.LNKTYPE,
            "link": "etc/rocky-release",
        }]))
        self.assertEqual(result["hardlink_count"], 1)

    def test_hardlink_missing_target_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "HARDLINK_TARGET_NOT_EARLIER_REGULAR"):
            audit.inspect_archive(make_archive([{
                "name": "test-link", "kind": tarfile.LNKTYPE,
                "link": "missing",
            }]))

    def test_hardlink_symlink_target_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "HARDLINK_TARGET_NOT_EARLIER_REGULAR"):
            audit.inspect_archive(make_archive([{
                "name": "test-link", "kind": tarfile.LNKTYPE,
                "link": "etc/os-release",
            }]))

    def test_hardlink_unsafe_target_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "UNSAFE_MEMBER_SEGMENT"):
            audit.inspect_archive(make_archive([{
                "name": "test-link", "kind": tarfile.LNKTYPE,
                "link": "../etc/rocky-release",
            }]))

    def test_regular_backslash_filename_accepted(self):
        result = audit.inspect_archive(make_archive([{
            "name": r"dir000/literal\\backslash", "content": b"data",
        }]))
        self.assertEqual(result["backslash_named_regular_count"], 1)

    def test_member_under_hardlink_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "MEMBER_UNDER_NON_DIRECTORY"):
            audit.inspect_archive(make_archive([
                {"name": "file-link", "kind": tarfile.LNKTYPE,
                 "link": "etc/rocky-release"},
                {"name": "file-link/child", "content": b"x"},
            ]))

    def test_duplicate_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "DUPLICATE_MEMBER"):
            audit.inspect_archive(make_archive([{"name": "dir000/file0000", "content": b"x"}]))

    def test_member_under_symlink_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "MEMBER_UNDER_SYMLINK"):
            audit.inspect_archive(make_archive([
                {"name": "shortcut", "kind": tarfile.SYMTYPE, "link": "dir000"},
                {"name": "shortcut/malicious", "content": b"x"},
            ]))

    def test_wrong_minor_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "ROCKY_RELEASE_MISMATCH"):
            audit.inspect_archive(make_archive(release="Rocky Linux release 9.9\n"))

    def test_symlink_chain_escape_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "SYMLINK_ESCAPES_ROOT"):
            audit.inspect_archive(make_archive([
                {"name": "var/base", "kind": tarfile.SYMTYPE, "link": "../../../usr"},
                {"name": "var/alias", "kind": tarfile.SYMTYPE, "link": "base/lib"},
            ]))

    def test_symlink_cycle_refused(self):
        with self.assertRaisesRegex(audit.AuditBlocked, "SYMLINK_LOOP_OR_DEPTH"):
            audit.inspect_archive(make_archive([
                {"name": "link1", "kind": tarfile.SYMTYPE, "link": "link2"},
                {"name": "link2", "kind": tarfile.SYMTYPE, "link": "link1"},
            ]))


if __name__ == "__main__":
    unittest.main()
