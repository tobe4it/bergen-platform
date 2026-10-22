"""Static and pure checks for read-only CT126 archive integrity preflight.

Never reads real archives or starts any zstd/tar command.
"""
import ast
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_metadata_archive_integrity_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-metadata-archive-integrity.yml"


class PaperlessArchiveIntegrityPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text()
        cls.tree = ast.parse(cls.source)
        cls.play_source = PLAY.read_text()
        cls.play = yaml.safe_load(cls.play_source)

    def test_python_valid_and_entrypoint_called(self):
        self.assertEqual(self.tree.body[-1].value.func.id, "main")

    def test_archive_identity_is_restricted_to_source_126(self):
        for token in ("vzdump-lxc-126-", "MAX_AGE = 48 * 3600",
                      "FRESH_CT126_ARCHIVE_NOT_FOUND",
                      "NEWEST_ARCHIVE_AMBIGUOUS", "MOUNT /", "MOUNT = Path("):
            self.assertIn(token, self.source)
        self.assertTrue(
            re.search(r"MAX_ARCHIVE_BYTES = 32 \* 1024\*\*3", self.source))

    def test_stream_checks_are_read_only_and_do_not_emit_member_names(self):
        for token in (
            'hashlib.sha256()',
            'stream.read(4 * 1024 * 1024)',
            'ARCHIVE_SHA256=digest',
            '["zstd", "-t", "-q", "--", str(path)]',
            '["tar", "--zstd", "-t", "-f", str(path)]',
            'stdout=subprocess.DEVNULL',
            'stderr=subprocess.DEVNULL',
            'ARCHIVE_CHANGED_DURING_CHECK',
        ):
            self.assertIn(token, self.source)
        for forbidden in (
            'write_text(', 'write_bytes(', 'open("wb"', 'open("w"',
            'subprocess.Popen(', 'shell=True', '"pct", "restore"',
            '"pct", "start"', '"pct", "set"', '"zfs", "create"',
            '"tar", "-x"', 'os.unlink(', 'os.remove(',
        ):
            self.assertNotIn(forbidden, self.source)

    def test_archive_preflight_does_not_claim_restore_or_db_recovery(self):
        for token in (
            '"RESTORE_PERFORMED": "NO"',
            '"CLONE_CREATED": "NO"',
            '"NETWORK_ISOLATION_PROVEN": "NO"',
            '"DATABASE_RECOVERY_PROVEN": "NO"',
        ):
            self.assertIn(token, self.source)

    def test_ansible_play_is_read_only_with_no_writes(self):
        self.assertEqual(len(self.play), 1)
        self.assertEqual(self.play[0]["hosts"], "venombox")
        self.assertIn("PAPERLESS_ARCHIVE_INTEGRITY_REQUIRES_READ_ONLY",
                      self.play_source)
        self.assertIn("PAPERLESS_ARCHIVE_INTEGRITY_NOT_PROVEN",
                      self.play_source)
        for item in self.play[0]["tasks"]:
            for forbidden in (
                "ansible.builtin.copy", "ansible.builtin.template",
                "ansible.builtin.systemd_service", "ansible.builtin.file",
                "ansible.builtin.shell", "ansible.builtin.script",
                "ansible.builtin.unarchive",
            ):
                self.assertNotIn(forbidden, item)


if __name__ == "__main__":
    unittest.main()
