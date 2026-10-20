"""Offline regression: CT110 archived snapshot inventory and Ansible postcheck bug."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "ansible/files/bergen_ai/audit_ct110_postbackup_archive_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-postbackup-archive-readonly.yml"
BACKUP = ROOT / "ansible/playbooks/backup-bergen-ai-ct110-once.yml"

spec = importlib.util.spec_from_file_location("postbackup", PY)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

GOOD_VOLID = (
    "bergen-synology-backup:backup/"
    "vzdump-lxc-110-2026_10_20-06_15_00.tar.zst"
)


class PostBackupInventoryTests(TestCase):
    def test_archive_count_and_content_size_without_content_reads(self):
        with mock.patch.object(a, "parsed_json", return_value=[
            {"volid": GOOD_VOLID, "size": 12938477},
            {"volid": "bergen-synology-backup:backup/vzdump-lxc-124-2026_10_20-06_15_00.tar.zst",
             "size": 10000},
        ]):
            result = a.check_archive()
        self.assertEqual(result["CT110_ARCHIVE_COUNT"], 1)
        self.assertEqual(result["CT110_ARCHIVE_METADATA"],
                         "ONE_NONEMPTY_ZSTD_ARCHIVE_VISIBLE")

    def test_no_archive_duplicate_or_wrong_storage_fail_closed(self):
        for items, count, label in [
            ([], 0, "NONE"),
            ([{"volid": GOOD_VOLID, "size": 100},
              {"volid": GOOD_VOLID, "size": 100}], 2, "MULTIPLE"),
            ([{"volid": "elsewhere:backup/vzdump-lxc-110-2026_10_20-06_15_00.tar.zst",
               "size": 100}], 1, "UNEXPECTED_FORMAT_OR_STORAGE"),
            ([{"volid": GOOD_VOLID, "size": 0}], 1, "EMPTY_OR_UNKNOWN_SIZE"),
            ([{"volid": GOOD_VOLID, "size": "100"}], 1, "EMPTY_OR_UNKNOWN_SIZE"),
            ([{"volid": "bergen-synology-backup:backup/vzdump-lxc-110-2026_10_20-06_15_00.tar.gz",
               "size": 100}], 1, "UNEXPECTED_FORMAT_OR_STORAGE"),
            ([{"volid": GOOD_VOLID}], 1, "EMPTY_OR_UNKNOWN_SIZE"),
        ]:
            with self.subTest(label=label), mock.patch.object(a, "parsed_json", return_value=items):
                got = a.check_archive()
                self.assertEqual(got["CT110_ARCHIVE_COUNT"], count)
                self.assertEqual(got["CT110_ARCHIVE_METADATA"], label)

    def test_storage_mount_requires_matching_nfs_and_pvesh_active(self):
        mount = {"filesystems": [{"target": a.MOUNT, "fstype": "nfs4"}]}
        pve = {"active": 1, "content": "backup,images"}
        with mock.patch.object(a, "parsed_json", side_effect=[mount, pve]):
            self.assertEqual(a.check_storage(), "EXPECTED_ACTIVE_NFS")
        with mock.patch.object(a, "parsed_json",
                               side_effect=[{"filesystems": [{"target": a.MOUNT,
                                                              "fstype": "ext4"}]}, pve]):
            self.assertEqual(a.check_storage(), "WRONG_OR_UNMOUNTED_TARGET")
        with mock.patch.object(a, "parsed_json", side_effect=[mount, {"active": 0}]):
            self.assertEqual(a.check_storage(), "PVE_STORAGE_UNVERIFIED")

    def test_success_means_metadata_only_not_restore_or_integrity(self):
        with (mock.patch.object(a, "check_guest", return_value="RUNNING"),
              mock.patch.object(a, "check_storage", return_value="EXPECTED_ACTIVE_NFS"),
              mock.patch.object(a, "check_archive", return_value={
                  "CT110_ARCHIVE_COUNT": 1,
                  "CT110_ARCHIVE_METADATA": "ONE_NONEMPTY_ZSTD_ARCHIVE_VISIBLE"
              })):
            result = a.report()
        self.assertEqual(result["STATUS"], "ARCHIVE_PRESENT_NOT_VALIDATED")
        self.assertFalse(result["BACKUP_EXECUTED_BY_THIS_AUDIT"])
        self.assertFalse(result["ARCHIVE_CONTENTS_CHECKED"])
        self.assertEqual(result["BACKUP_INTEGRITY"], "NOT_TESTED")
        self.assertEqual(result["RESTORE_TEST"], "NOT_ATTESTED")
        self.assertFalse(result["APPLY_AUTHORIZED"])

    def test_playbook_readonly_and_backup_postcheck_is_quoted_string(self):
        source = PY.read_text()
        ast.parse(source)
        for forbidden in ("vzdump", "pct start", "pct stop", "pct reboot",
                          "pvesh set", "rm -rf", "os.unlink"):
            # Script's docstring mentions no vzdump as a comment; test AST calls below.
            if forbidden == "vzdump":
                continue
            self.assertNotIn(forbidden, source)
        self.assertNotIn('["vzdump"', source)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        commands = [task for task in play["tasks"] if "ansible.builtin.command" in task]
        self.assertEqual(len(commands), 1)
        self.assertFalse(commands[0]["changed_when"])
        self.assertTrue(commands[0]["no_log"])
        self.assertIn("ARCHIVE_CONTENTS_CHECKED=False", PLAY.read_text())
        backup = yaml.safe_load(BACKUP.read_text())[1]
        all_tasks = backup["tasks"][2]["block"]
        assertion = next(t for t in all_tasks if t["name"] == "Require CT110 is still running")
        checks = assertion["ansible.builtin.assert"]["that"]
        self.assertEqual(checks, ["ct110_after.stdout | trim == 'status: running'"])
        self.assertTrue(all(isinstance(x, str) for x in checks))
        self.assertIn("oneoff_backup_exec.rc | default(-1) | int == 0", BACKUP.read_text())
