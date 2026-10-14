"""Static safety tests for the read-only Synology archive preflight."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/synology_archive_preflight.py"
PLAYBOOK = ROOT / "ansible/playbooks/audit-paperless-synology-archive.yml"


class ArchivePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.play = PLAYBOOK.read_text(encoding="utf-8")

    def test_syntax(self):
        compile(self.script, str(SCRIPT), "exec")

    def test_read_only(self):
        for forbidden in (".unlink(", ".rename(", "os.rename(", "os.replace(",
                          "os.mkdir(", "os.chmod(", "os.chown(", "shutil.move("):
            self.assertNotIn(forbidden, self.script)
        self.assertIn("NO_FILES_CHANGED", self.script)

    def test_critical_gates(self):
        for gate in ("CROSS_DEVICE_RENAME_NOT_ATOMIC",
                     "FILENAME_VERSIONED_RECEIPTS_NOT_IMPLEMENTED",
                     "PREPARED_RECEIPT_NEEDS_RECONCILIATION",
                     "FILENAME_REUSE_OR_CHANGED_SOURCE",
                     "DSM_DELETE_CHILD_AND_RENAME"):
            self.assertIn(gate, self.script)

    def test_run_under_unprivileged_account(self):
        self.assertIn("RUN_AS_CONFIGURED_SYNC_USER_ONLY", self.script)
        self.assertIn("sudo -n -u {{ synology_config.sync_user | quote }}", self.play)
        self.assertIn("changed_when: false", self.play)
        self.assertNotIn("paperless_archive_apply", self.play)


if __name__ == "__main__":
    unittest.main()
