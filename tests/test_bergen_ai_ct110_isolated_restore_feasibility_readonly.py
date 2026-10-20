"""Fail-closed CT110 isolated restore rehearsal candidate inventory tests."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_isolated_restore_feasibility_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-isolated-restore-feasibility-readonly.yml"
spec = importlib.util.spec_from_file_location("restore_feasibility", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

GOOD_CONFIG = ("hostname: bergen-ai\n"
               "rootfs: local-zfs:subvol-110-disk-0,size=36G\n"
               "net0: name=eth0,bridge=vmbr0,ip=dhcp\n")
BACKUP_VOLID = ("bergen-synology-backup:backup/"
                "vzdump-lxc-110-2026_10_20-06_15_00.tar.zst")


class RestoreFeasibilityTest(TestCase):
    def test_rootfs_storage_requires_expected_source_storage_and_size(self):
        with mock.patch.object(a, "command", return_value=GOOD_CONFIG):
            self.assertEqual(a.source_storage(), ("local-zfs", 36))
        for text in (
            GOOD_CONFIG.replace("local-zfs", "external"),
            GOOD_CONFIG.replace("size=36G", "size=2G"),
            GOOD_CONFIG + "rootfs: local-zfs:other,size=36G\n",
            GOOD_CONFIG.replace("size=36G", "size=5T"),
            "",
        ):
            with self.subTest(text=text), mock.patch.object(a, "command", return_value=text):
                self.assertIsNone(a.source_storage())

    def test_candidate_id_requires_cluster_and_local_index_to_be_unused(self):
        resources = [{"vmid": 110}, {"vmid": 124}, {"vmid": 816}]
        with (mock.patch.object(a, "json_cmd", return_value=resources),
              mock.patch.object(a, "command", return_value="VMID Status Lock Name\n110 running - bergen-ai\n")):
            self.assertEqual(a.candidate_unused(), "UNUSED_AT_CHECK_TIME")
        with (mock.patch.object(a, "json_cmd", return_value=resources + [{"vmid": 910}]),
              mock.patch.object(a, "command", return_value="VMID Status Lock Name\n")):
            self.assertEqual(a.candidate_unused(), "IN_USE")
        with (mock.patch.object(a, "json_cmd", return_value=resources),
              mock.patch.object(a, "command", return_value="VMID Status Lock Name\n910 stopped - restored\n")):
            self.assertEqual(a.candidate_unused(), "IN_USE")
        with mock.patch.object(a, "json_cmd", return_value=None):
            self.assertEqual(a.candidate_unused(), "UNVERIFIED")

    def test_storage_capacity_needs_local_zfs_active_with_rootdir_and_buffer(self):
        good = {"active": 1, "type": "zfspool", "content": "images,rootdir",
                "avail": 60 * a.GIB}
        with mock.patch.object(a, "json_cmd", return_value=good):
            self.assertEqual(a.storage_capacity(("local-zfs", 36)),
                             "ACTIVE_ROOTDIR_ZFS_WITH_BUFFER")
        for fields, expected in (
            ({"active": 0}, "STORAGE_INACTIVE"),
            ({"type": "dir"}, "NOT_ROOTDIR_ZFS_STORAGE"),
            ({"content": "backup"}, "NOT_ROOTDIR_ZFS_STORAGE"),
            ({"avail": 40 * a.GIB}, "INSUFFICIENT_CAPACITY_WITH_BUFFER"),
            ({"avail": "100000000000"}, "UNVERIFIED"),
        ):
            with self.subTest(fields=fields):
                with mock.patch.object(a, "json_cmd", return_value={**good, **fields}):
                    self.assertEqual(a.storage_capacity(("local-zfs", 36)), expected)

    def test_nfs_storage_requires_correct_mounted_fs_and_active_backup(self):
        fs = {"filesystems": [{"target": "/mnt/pve/bergen-synology-backup",
                               "fstype": "nfs4"}]}
        active = {"active": True, "content": "backup,images"}
        with mock.patch.object(a, "json_cmd", side_effect=[fs, active]):
            self.assertEqual(a.backup_nfs(), "EXPECTED_ACTIVE_NFS")
        with mock.patch.object(a, "json_cmd", side_effect=[
                {"filesystems": [{"target": "/mnt/pve/bergen-synology-backup",
                                  "fstype": "ext4"}]}, active]):
            self.assertEqual(a.backup_nfs(), "UNVERIFIED")
        with mock.patch.object(a, "json_cmd", side_effect=[fs, {"active": 0}]):
            self.assertEqual(a.backup_nfs(), "UNVERIFIED")

    def test_exactly_one_nonempty_ct110_archive_metadata(self):
        good = [{"volid": BACKUP_VOLID, "size": 12345678},
                {"volid": "bergen-synology-backup:backup/vzdump-lxc-124-2026_10_20-06_15_00.tar.zst",
                 "size": 654321}]
        with mock.patch.object(a, "json_cmd", return_value=good):
            self.assertEqual(a.archive_metadata(), "ONE_NONEMPTY_CT110_ZSTD_ARCHIVE")
        for arr, expected in (
            ([], "NO_UNIQUE_CT110_ARCHIVE"),
            ([good[0], good[0]], "NO_UNIQUE_CT110_ARCHIVE"),
            ([{"volid": BACKUP_VOLID, "size": 0}], "ARCHIVE_METADATA_UNEXPECTED"),
            ([{"volid": BACKUP_VOLID, "size": "123"}], "ARCHIVE_METADATA_UNEXPECTED"),
            ([{"volid": BACKUP_VOLID.replace("bergen-synology-backup", "other"),
               "size": 123}], "ARCHIVE_METADATA_UNEXPECTED"),
        ):
            with self.subTest(expected=expected), mock.patch.object(a, "json_cmd", return_value=arr):
                self.assertEqual(a.archive_metadata(), expected)

    def test_full_report_is_only_candidate_not_restore_or_network_clearance(self):
        with (mock.patch.object(a, "command", return_value="status: running"),
              mock.patch.object(a, "source_storage", return_value=("local-zfs", 36)),
              mock.patch.object(a, "candidate_unused", return_value="UNUSED_AT_CHECK_TIME"),
              mock.patch.object(a, "storage_capacity", return_value="ACTIVE_ROOTDIR_ZFS_WITH_BUFFER"),
              mock.patch.object(a, "backup_nfs", return_value="EXPECTED_ACTIVE_NFS"),
              mock.patch.object(a, "archive_metadata",
                                return_value="ONE_NONEMPTY_CT110_ZSTD_ARCHIVE")):
            result = a.report()
        self.assertEqual(result["STATUS"], "RESTORE_ENVIRONMENT_CANDIDATE")
        self.assertFalse(result["RESTORE_EXECUTED"])
        self.assertFalse(result["RESTORE_AUTHORIZED"])
        self.assertFalse(result["NEW_GUEST_CREATED"])
        self.assertFalse(result["GUEST_STARTED"])
        self.assertEqual(result["NETWORK_ISOLATION"], "NOT_PROVEN")
        self.assertEqual(result["ARCHIVE_CONFIG_SANITIZATION"], "NOT_PROVEN")
        self.assertEqual(result["RESTORE_TEST"], "NOT_ATTESTED")
        self.assertFalse(result["APPLY_AUTHORIZED"])

    def test_readonly_command_whitelist_and_ansible_yaml(self):
        code = SCRIPT.read_text()
        ast.parse(code)
        self.assertNotIn('"pct", "restore"', code)
        self.assertNotIn('"pct", "start"', code)
        self.assertNotIn('"pct", "stop"', code)
        self.assertNotIn('"pct", "create"', code)
        self.assertNotIn('"pct", "set"', code)
        self.assertNotIn('["vzdump"', code)
        self.assertNotIn('"pvesh", "create"', code)
        self.assertNotIn("rm -rf", code)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        commands = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertFalse(commands[0]["changed_when"])
        self.assertTrue(commands[0]["no_log"])
        self.assertIn("RESTORE_AUTHORIZED=False", PLAY.read_text())
