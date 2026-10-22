"""Ensure CT790 backup candidate audit never creates a backup or mount."""
import importlib.util
from pathlib import Path
from unittest import TestCase, mock
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/nextcloud/audit_ct790_backup_candidates_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-backup-candidates-readonly.yml"
spec = importlib.util.spec_from_file_location("ct790_backup_probe", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BackupReadOnlyTests(TestCase):
    def test_code_is_bounded_and_read_only(self):
        source = SCRIPT.read_text()
        for required in ("O_NOFOLLOW", "O_NOATIME", "os.stat(",
                         "follow_symlinks=False", "findmnt", '"zfs", "list"',
                         "archive_integrity_proven", "restore_test_proven",
                         "backup_recoverability_proven"):
            self.assertIn(required, source)
        for forbidden in ("os.unlink(", "os.remove(", "os.write(",
                          "os.rename(", "os.replace(", "os.mkdir(",
                          "os.makedirs(", "os.chmod(", "os.chown(",
                          "open(path, 'w')", "shell=True", '"zfs", "snapshot"',
                          '"zfs", "rollback"', '"pvesm", "status"',
                          '"pct", "start"', '"vzdump",'):
            self.assertNotIn(forbidden, source)

    def test_exact_candidate_names_only(self):
        self.assertIsNotNone(module.BACKUP_RE.fullmatch(
            "vzdump-lxc-790-2026_10_22-17_41_00.tar.zst"))
        for disallowed in (
            "vzdump-lxc-701-2026_10_22-17_41_00.tar.zst",
            "vzdump-lxc-790-2026_10_22-17_41_00.tar.zst.partial",
            "vzdump-lxc-790-2026_10_22-17_41_00.tar.zst/../file",
            "vzdump-qemu-790-2026_10_22-17_41_00.tar.zst"):
            self.assertIsNone(module.BACKUP_RE.fullmatch(disallowed))
        self.assertIsNotNone(module.DATASET_RE.fullmatch("rpool/data/subvol-790-disk-0"))
        self.assertIsNone(module.DATASET_RE.fullmatch("rpool/data/subvol-701-disk-0"))

    def test_missing_preexisting_nfs_does_not_try_mount(self):
        with mock.patch.object(module, "verified_nfs_mount", return_value=False):
            r = module.backup_candidates()
        self.assertEqual(r["candidate_count"], 0)
        self.assertFalse(r["archive_integrity_proven"])
        self.assertFalse(r["restore_test_proven"])

    def test_snapshot_inventory_scope(self):
        fake = mock.Mock(returncode=0,
                         stdout="rpool/data/subvol-790-disk-0@before\t1792690000\n",
                         stderr="")
        with mock.patch.object(module, "exec_readonly", return_value=fake) as run:
            r = module.snapshots("rpool/data/subvol-790-disk-0")
            self.assertEqual(run.call_args[0][0][:3],
                             ["zfs", "list", "-H"])
        self.assertEqual(r["snapshot_count"], 1)
        self.assertFalse(r["snapshot_recovery_proven"])

    def test_fail_closed_on_other_dataset(self):
        with mock.patch.object(module, "exec_readonly",
                               return_value=mock.Mock(returncode=0,
                               stdout="rpool/data/subvol-701-disk-0@wrong\t1792690000\n",
                               stderr="")):
            with self.assertRaises(module.Refused):
                module.snapshots("rpool/data/subvol-790-disk-0")

    def test_ansible_command_allowlist(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(plays[0]["import_playbook"],
                         "audit-rocky-9-8-ct790-sanitization-targets-readonly.yml")
        self.assertEqual(plays[1]["hosts"], "venombox")
        commands = []
        for task in plays[1]["tasks"]:
            mods = [x for x in task if x.startswith("ansible.builtin.")]
            self.assertEqual(len(mods), 1, task["name"])
            self.assertIn(mods[0], ("ansible.builtin.command",
                                    "ansible.builtin.assert",
                                    "ansible.builtin.debug"))
            if mods[0] == "ansible.builtin.command":
                self.assertIs(task["changed_when"], False)
                argv = task["ansible.builtin.command"]["argv"]
                commands.append(argv)
                self.assertTrue(argv in (["pct", "status", "790"],
                                         ["pct", "config", "701"])
                                or argv[:2] == ["python3", "-c"])
                if argv[:2] == ["python3", "-c"]:
                    self.assertIs(task.get("no_log"), True)
        self.assertEqual(len(commands), 4)
        source = PLAY.read_text()
        self.assertIn("backup_recoverability_proven: false", source)
        self.assertIn("sanitation_authorized: false", source)
        self.assertIn("pct_template_authorized: false", source)

if __name__ == "__main__":
    unittest.main()
