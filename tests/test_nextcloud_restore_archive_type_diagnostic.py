"""Synthetic, offline-only TAR member classification tests."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "ansible/files/nextcloud/diagnose_restore_archive_member_types.py"
)
spec = importlib.util.spec_from_file_location("nextcloud_archive_diag", SCRIPT)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class NextcloudArchiveTypesTest(unittest.TestCase):
    def test_valid_and_unsafe_relative_symlink_targets(self):
        link = tarfile.TarInfo("html/apps/example")
        link.type = tarfile.SYMTYPE
        link.linkname = "../data/example.txt"
        self.assertEqual(diag.link_kind(link), "inside_html_namespace")
        link.linkname = "../../../etc/passwd"
        self.assertEqual(diag.link_kind(link), "outside_html_namespace")
        link.linkname = "/etc/passwd"
        self.assertEqual(
            diag.link_kind(link), "unsafe_absolute_empty_or_platform_path"
        )

    def test_hardlink_target(self):
        item = tarfile.TarInfo("html/data/linked")
        item.type = tarfile.LNKTYPE
        item.linkname = "html/data/real"
        self.assertEqual(diag.link_kind(item), "inside_html_namespace")

    def test_bounded_counts_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "example.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                folder = tarfile.TarInfo("html")
                folder.type = tarfile.DIRTYPE
                tar.addfile(folder)
                sub = tarfile.TarInfo("html/data")
                sub.type = tarfile.DIRTYPE
                tar.addfile(sub)
                payload = b"diagnostic test only"
                file = tarfile.TarInfo("html/data/real")
                file.size = len(payload)
                tar.addfile(file, io.BytesIO(payload))
                hard = tarfile.TarInfo("html/data/hard")
                hard.type = tarfile.LNKTYPE
                hard.linkname = "html/data/real"
                tar.addfile(hard)
                symlink = tarfile.TarInfo("html/data/alias")
                symlink.type = tarfile.SYMTYPE
                symlink.linkname = "real"
                tar.addfile(symlink)
                escaping = tarfile.TarInfo("html/data/escaping")
                escaping.type = tarfile.SYMTYPE
                escaping.linkname = "../../../../etc/passwd"
                tar.addfile(escaping)
                pipe = tarfile.TarInfo("html/data/pipe")
                pipe.type = tarfile.FIFOTYPE
                tar.addfile(pipe)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            report = diag.read_report(archive, digest)
            self.assertEqual(report["member_count"], 7)
            self.assertEqual(report["entry_types"]["hard_link"], 1)
            self.assertEqual(report["entry_types"]["symbolic_link"], 2)
            self.assertEqual(report["entry_types"]["fifo"], 1)
            self.assertEqual(report["link_targets"]["inside_html_namespace"], 2)
            self.assertEqual(report["link_targets"]["outside_html_namespace"], 1)
            self.assertEqual(report["invalid_archive_paths"], 0)
            self.assertTrue(report["archive_sha256_matches_pinned"])
            self.assertFalse(report["archive_extracted"])
            with self.assertRaises(diag.DiagnosticError):
                diag.read_report(archive, "0" * 64)

    def test_path_safety_and_secret_free_report(self):
        for value in ("html/config.php", "html/data/", "nextcloud.sql.gz"):
            self.assertTrue(diag.path_ok(value))
        for value in ("/etc/passwd", "html/../outside", "../bad", "html//double"):
            self.assertFalse(diag.path_ok(value))


if __name__ == "__main__":
    unittest.main()
