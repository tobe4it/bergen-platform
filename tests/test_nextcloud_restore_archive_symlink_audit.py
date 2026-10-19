"""Synthetic, non-production tests for fail-closed Nextcloud symlink audit."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "ansible/files/nextcloud/audit_verified_restore_archive.py"
)
spec = importlib.util.spec_from_file_location("nextcloud_archive_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class TestSafeLinks(unittest.TestCase):
    def test_simple_internal_link(self):
        audit.validate_symbolic_links(
            {"html", "html/data", "html/data/file", "html/data/alias"},
            {"html/data/alias": "file"},
        )

    def test_internal_link_chain(self):
        audit.validate_symbolic_links(
            {"html", "html/apps", "html/lib", "html/lib/module",
             "html/apps/alias", "html/apps/second"},
            {"html/apps/alias": "../lib/module",
             "html/apps/second": "alias"},
        )

    def test_external_traversal_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "SYMLINK_ESCAPE"):
            audit.validate_symbolic_links(
                {"html", "html/data", "html/data/escape"},
                {"html/data/escape": "../../../etc/passwd"},
            )

    def test_indirect_external_traversal_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "SYMLINK_CHAIN_ESCAPE"):
            audit.validate_symbolic_links(
                {"html", "html/data", "html/data/redirect", "html/data/alias"},
                {"html/data/redirect": "../../../tmp",
                 "html/data/alias": "redirect"},
            )

    def test_cycles_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "SYMLINK_CYCLE"):
            audit.validate_symbolic_links(
                {"html", "html/a", "html/b"},
                {"html/a": "b", "html/b": "a"},
            )

    def test_parent_symlink_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "SYMLINK_USED_AS_ARCHIVE_PARENT"):
            audit.validate_symbolic_links(
                {"html", "html/real", "html/path", "html/path/deceptive"},
                {"html/path": "real"},
            )

    def test_dangling_link_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "DANGLING_SYMLINK_TARGET"):
            audit.validate_symbolic_links(
                {"html", "html/missing"}, {"html/missing": "no_such_file"}
            )

    def test_absolute_link_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "UNSAFE_SYMLINK_TARGET"):
            audit.validate_symbolic_links(
                {"html", "html/absolute"}, {"html/absolute": "/etc/passwd"}
            )


if __name__ == "__main__":
    unittest.main()
