"""Offline safety tests for CT110's manually authorized one-time backup."""
import ast
import importlib.util
import json
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/preflight_ct110_oneoff_backup.py"
PREFLIGHT = ROOT / "ansible/playbooks/preflight-bergen-ai-ct110-oneoff-backup-readonly.yml"
ONEOFF = ROOT / "ansible/playbooks/backup-bergen-ai-ct110-once.yml"
spec = importlib.util.spec_from_file_location("ai_oneoff_backup", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class BergenAiOneOffTest(TestCase):
    def test_guest_identity_and_extra_mounts_fail_closed(self):
        cfg = (
            "hostname: bergen-ai\n"
            "unprivileged: 1\n"
            "rootfs: local-zfs:subvol-110-disk-0,size=36G\n"
            "net0: name=eth0,bridge=vmbr1\n"
            "lxc.mount.entry: /dev/fuse dev/fuse none bind,optional,create=file\n"
        )
        self.assertEqual(a.guest_config(cfg, "status: running\n"),
                         "RUNNING_ROOTFS_ONLY")
        self.assertEqual(a.guest_config(cfg.replace("bergen-ai", "not-ai"), "status: running"),
                         "UNVERIFIED")
        self.assertEqual(a.guest_config(cfg, "status: stopped"), "UNVERIFIED")
        self.assertEqual(a.guest_config(cfg.replace(
            "lxc.mount.entry: /dev/fuse dev/fuse none bind,optional,create=file\n", ""),
            "status: running"), "EXTRA_MOUNTS_REQUIRE_REVIEW")
        self.assertEqual(a.guest_config(cfg.replace(
            "bind,optional,create=file\n", "bind,optional,create=file 0 0\n"),
            "status: running"), "RUNNING_ROOTFS_ONLY")
        self.assertEqual(a.guest_config(cfg + "mp0: /host/data,mp=/data\n",
                                        "status: running"), "EXTRA_MOUNTS_REQUIRE_REVIEW")
        self.assertEqual(a.guest_config(cfg.replace("/dev/fuse dev/fuse", "/etc/private dev/fuse"),
                                        "status: running"), "EXTRA_MOUNTS_REQUIRE_REVIEW")
        self.assertEqual(a.guest_config(cfg + "lxc.mount.entry: /x /y none bind 0 0\n",
                                        "status: running"), "EXTRA_MOUNTS_REQUIRE_REVIEW")
        self.assertEqual(a.guest_config(cfg + "exclude-path: /srv/ai\n",
                                        "status: running"), "EXCLUSION_OR_UNSAFE_GUEST_CONFIG")

    def test_persistent_webui_must_be_inside_guest_rootfs(self):
        def command(argv, timeout=12, limit=220000):
            if "test" in argv:
                return ""
            return "/"
        with mock.patch.object(a, "command", side_effect=command):
            self.assertEqual(a.persistent_data(), "IN_GUEST_ROOTFS")
        with mock.patch.object(a, "command", return_value=None):
            self.assertEqual(a.persistent_data(), "UNVERIFIED")

    def test_guest_mount_scan_rejects_external_volume(self):
        safe = {"filesystems": [{"target": "/", "fstype": "zfs",
                                 "children": [{"target": "/dev/shm", "fstype": "tmpfs"}]}]}
        external = {"filesystems": [{"target": "/", "fstype": "zfs",
                                     "children": [{"target": "/data", "fstype": "nfs4"}]}]}
        with mock.patch.object(a, "command", return_value=json.dumps(safe)):
            self.assertEqual(a.guest_mounts(), "NO_EXTERNAL_MOUNTS_DETECTED")
        with mock.patch.object(a, "command", return_value=json.dumps(external)):
            self.assertEqual(a.guest_mounts(), "EXTERNAL_OR_UNKNOWN_MOUNT")
        with mock.patch.object(a, "command", return_value="not-json"):
            self.assertEqual(a.guest_mounts(), "UNVERIFIED")

    def test_script_no_write_and_does_not_authorize_network_changes(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        self.assertIn('APPLY_AUTHORIZED=False', source)
        self.assertIn('BACKUP_EXECUTED=False', source)
        self.assertIn('r"^mp[0-9]+:\\s"', source)
        for forbidden in ("pct set", "pct stop", "pct start", "pct reboot",
                          "vzdump --", "pvesh set", "os.unlink", "rm -rf",
                          "ifreload -a", "nft add", "iptables -A"):
            self.assertNotIn(forbidden, source)

    def test_anisble_preflight_has_no_write_operation(self):
        playbooks = yaml.safe_load(PREFLIGHT.read_text())
        self.assertEqual(playbooks[0]["import_playbook"], "audit-bergen-ai-ct110-persistent-data-readonly.yml")
        play = playbooks[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        commands = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        self.assertIn("BACKUP_EXECUTED=False", PREFLIGHT.read_text())
        self.assertIn("ct110_backup_ready:", PREFLIGHT.read_text())
        self.assertIn("data_scope.STATUS == 'KNOWN_DATA_PATHS_IN_ROOTFS'", PREFLIGHT.read_text())

    def test_single_backup_has_explicit_separate_gates_and_no_prune(self):
        plays = yaml.safe_load(ONEOFF.read_text())
        self.assertEqual(plays[0]["import_playbook"],
                         "preflight-bergen-ai-ct110-oneoff-backup-readonly.yml")
        second = plays[1]
        self.assertEqual(second["hosts"], "venombox")
        self.assertEqual(second["vars"]["bergen_ai_ct110_oneoff_approval"], "")
        content = ONEOFF.read_text()
        self.assertIn("APPROVE_CT110_SNAPSHOT_BACKUP_ONCE", content)
        self.assertIn("ct110_preflight.SAFE_TO_ATTEMPT_SINGLE_BACKUP", content)
        self.assertIn("ct110_backup_ready | bool", content)
        self.assertIn("data_scope.PODMAN_NAMED_VOLUMES == 'NONE'", content)
        self.assertIn("SAFE_TO_ATTEMPT_SINGLE_BACKUP", content)
        self.assertIn("vzdump", content)
        self.assertIn("- snapshot", content)
        self.assertIn("- keep-all=1", content)
        self.assertIn("- '0'", content)
        self.assertIn("no_log: true", content)
        self.assertNotIn("systemctl", content)
        self.assertNotIn("pct reboot", content)
        self.assertNotIn("- --mode\n              - stop", content)
        self.assertNotIn("- --remove\n              - '1'", content)


if __name__ == "__main__":
    import unittest
    unittest.main()
