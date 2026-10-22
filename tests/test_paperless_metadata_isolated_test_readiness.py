"""Safety gates for Paperless isolated restore feasibility audit.

No production or test container is created here.
"""
import ast
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_isolated_metadata_clone_readiness.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-metadata-isolated-test-readiness.yml"


class IsolatedCloneFeasibilityAudit(unittest.TestCase):
    def test_python_source_is_syntax_valid_and_unconditionally_runs(self):
        nodes = ast.parse(SCRIPT.read_text()).body
        self.assertEqual(nodes[-1].value.func.id, "main")

    def test_source_is_only_read_only_proxmox_backup_inventory(self):
        source = SCRIPT.read_text()
        for token in (
            '"pct", "config", "126"',
            '"findmnt", "--mountpoint", BACKUP_ROOT',
            'BACKUP_RECENT="YES"',
            'CLONE_CREATED": "NO"',
            'RESTORE_TESTED": "NO"',
            'NETWORK_ISOLATION_PROVEN": "NO"',
            'POSTGRES_INTEGRATION_TESTED": "NO"',
            '0 <= now-st.st_mtime <= 48*3600',
            'not file.is_file()',
            'max(candidates)[1]',
        ):
            self.assertIn(token, source)
        for token in (
            '"pct", "restore"', '"pct", "start"',
            'pg_restore', 'psql', 'podman', 'docker',
            'rm -rf', 'mkdir(', 'write_text(',
            'assign_perm(', 'remove_perm(',
        ):
            self.assertNotIn(token, source)

    def test_playbook_refuses_write_modes_and_preserves_logs(self):
        body = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(body), 1)
        play = body[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        src = PLAY.read_text()
        for marker in (
            'paperless_taxonomy_apply_approved',
            'paperless_metadata_timer_activate',
            'paperless_linked_metadata_apply_approved',
            'ISOLATED_METADATA_TEST_REQUIRES_READ_ONLY',
            'RESTORE_TESTED=NO',
            'NETWORK_ISOLATION_PROVEN=NO',
            'POSTGRES_INTEGRATION_TESTED=NO',
        ):
            self.assertIn(marker, src)
        for task in play["tasks"]:
            for forbidden in (
                "ansible.builtin.copy", "ansible.builtin.file",
                "ansible.builtin.systemd_service",
                "ansible.builtin.template",
            ):
                self.assertNotIn(forbidden, task)


if __name__ == "__main__":
    unittest.main()
