"""Policy checks for read-only Synology native ACL audit."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_synology_scan_acls.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-synology-acls.yml"


class SynologyAclAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.play = PLAY.read_text(encoding="utf-8")

    def test_python_compiles(self):
        compile(self.script, str(SCRIPT), "exec")

    def test_no_mutating_commands(self):
        for forbidden in ("os.rename(", "os.replace(", ".unlink(", ".mkdir(", "os.mkdir(",
                          "os.chmod(", "os.chown(", "setfacl", "-add", "-del", "-replace"):
            self.assertNotIn(forbidden, self.script)
        self.assertIn('[tool, "-get", str(path)]', self.script)
        self.assertIn("NO_FILES_CHANGED", self.script)

    def test_acl_evidence_is_not_automatically_approved(self):
        self.assertIn("REVIEW_REQUIRED", self.script)
        self.assertIn("ACL_QUERY_FAILED", self.script)
        self.assertIn("ACL_OUTPUT_TRUNCATED", self.script)
        self.assertIn("ROOT_READ_ONLY_ACL_AUDIT_REQUIRED", self.script)
        self.assertIn("changed_when: false", self.play)
        self.assertIn("sudo -n /usr/bin/python3 -", self.play)


if __name__ == "__main__":
    unittest.main()
