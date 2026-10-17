"""Static safety checks for Synology archive mount audit."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_synology_archive_mounts.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-synology-mounts.yml"


class MountAuditTests(unittest.TestCase):
    def test_syntax(self):
        compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")

    def test_read_only(self):
        s = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (".mkdir(", "os.mkdir(", "os.rename(", "os.replace(",
                          ".unlink(", "os.chmod(", "os.chown(", "subprocess.run("):
            self.assertNotIn(forbidden, s)
        self.assertIn('Path("/proc/self/mountinfo")', s)
        self.assertIn("ARCHIVE_LOCATION_APPROVED", s)
        self.assertIn("NO_FILES_CHANGED", s)

    def test_ansible_never_changes_nas(self):
        p = PLAY.read_text(encoding="utf-8")
        self.assertIn("changed_when: false", p)
        self.assertIn("sudo -n /usr/bin/python3 -", p)
        self.assertNotIn("paperless_archive_apply", p)


if __name__ == "__main__":
    unittest.main()
