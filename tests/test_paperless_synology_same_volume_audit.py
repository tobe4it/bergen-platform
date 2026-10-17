"""Read-only mount audit policy tests."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_synology_same_volume_archive.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-synology-same-volume.yml"


class SameVolumeAuditTests(unittest.TestCase):
    def test_python_compiles(self):
        compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")

    def test_read_only(self):
        s = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("os.mkdir(", ".mkdir(", ".unlink(", "os.rename(", "os.replace(",
                          "shutil.move(", "os.chmod(", "os.chown("):
            self.assertNotIn(forbidden, s)
        self.assertIn("NO_FILES_CHANGED", s)
        self.assertIn("DSM_ACL_REVIEW_REQUIRED", s)
        self.assertIn("SAME_VOLUME", s)
        self.assertIn("secure_state()", s)

    def test_unprivileged_execution(self):
        s = SCRIPT.read_text(encoding="utf-8")
        p = PLAY.read_text(encoding="utf-8")
        self.assertIn("RESTRICTED_USER_REQUIRED", s)
        self.assertIn("sudo -n -u {{ synology_config.sync_user | quote }}", p)
        self.assertIn("changed_when: false", p)
        self.assertNotIn("paperless_archive_apply", p)


if __name__ == "__main__":
    unittest.main()
