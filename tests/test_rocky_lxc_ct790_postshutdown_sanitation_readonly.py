#!/usr/bin/env python3
"""Fail-closed stopped CT790 sanitation inventory, no writes and no key exposure."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/nextcloud/inventory_ct790_stopped_rootfs_sanitation.py"
PLAY = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-postshutdown-sanitization-readonly.yml"
spec = importlib.util.spec_from_file_location("ct790_rootfs_survey", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class StoppedSanitationInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.raw)
        cls.tasks = cls.plays[1]["tasks"]

    def test_stopped_only_audit_and_preexisting_exact_zfs_mount(self):
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-rootfs-release-readonly.yml",
        })
        self.assertEqual(len(self.plays), 2)
        play = self.plays[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIs(play["become"], True)
        self.assertIs(play["gather_facts"], False)
        self.assertIs(play["any_errors_fatal"], True)
        for s in (
            "rocky_release_zfs_mounted.stdout | trim == 'yes'",
            "rocky_sanitation_mounted.stdout | trim == 'yes'",
            "rocky_sanitation_findmnt.stdout == rocky_release_findmnt.stdout",
            "rocky_post_dataset",
            "local-zfs:subvol-790-disk-",
            "'status: stopped' in rocky_post_state.stdout_lines",
            "'status: stopped' in rocky_sanitation_before_status.stdout_lines",
            "'status: stopped' in rocky_sanitation_after_status.stdout_lines",
            "inventory_ct790_stopped_rootfs_sanitation.py",
            "ROCKY_9_8_CT790_POSTSHUTDOWN_SANITATION_READ_ONLY_INVENTORIED",
            "REVIEW_REQUIRED_NO_CHANGES_AUTHORIZED",
            "rocky_sanitation_ct701_config_after.stdout == rocky_post_ct701.stdout",
        ):
            self.assertIn(s, self.raw)

    def test_whitelisted_no_write_pve_zfs_and_helper_commands(self):
        commands = []
        for task in self.tasks:
            modules = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, msg=task["name"])
            self.assertIn(modules[0], ("ansible.builtin.command",
                                      "ansible.builtin.assert",
                                      "ansible.builtin.debug"))
            cmd = task.get("ansible.builtin.command")
            if not cmd:
                continue
            self.assertIs(task["changed_when"], False)
            argv = cmd["argv"]
            commands.append(argv)
            self.assertTrue(
                argv in ([ "pct", "status", "790" ],
                         [ "pct", "config", "701" ]) or
                argv[:3] == ["zfs", "get", "-H"] or
                argv[:2] == ["findmnt", "-rn"] or
                argv[:2] == ["python3", "-c"], msg=task["name"])
            if argv[:2] == ["python3", "-c"] or argv == ["pct", "config", "701"]:
                self.assertIs(task.get("no_log"), True)
        self.assertEqual(len(commands), 6)
        self.assertEqual(sum(x == ["pct", "status", "790"] for x in commands), 2)
        for forbidden in (
            "argv: [pct, start", "argv: [pct, stop",
            "argv: [pct, exec", "argv: [pct, shutdown",
            "argv: [pct, mount", "argv: [pct, template",
            "argv: [pct, set", "argv: [zfs, mount",
            "ansible.builtin.copy:", "ansible.builtin.file:",
            "ansible.builtin.raw:", "ansible.builtin.shell:",
            "ansible.builtin.systemd:",
        ):
            self.assertNotIn(forbidden, self.raw)

    def test_empty_set_machine_identity_and_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as root:
            etc = Path(root) / "etc"
            etc.mkdir()
            mid = etc / "machine-id"
            mid.write_text("0123456789abcdef0123456789abcdef\n")
            fd = os.open(root, helper.DIR_FLAGS)
            try:
                val = helper.inspect_path(fd, "etc/machine-id", want_machine_id=True)
                self.assertEqual(val["state"], "SET_32HEX")
                self.assertNotIn("0123456789abcdef", str(val))
                mid.write_text("")
                self.assertEqual(helper.inspect_path(
                    fd, "etc/machine-id", want_machine_id=True)["state"], "EMPTY")
                mid.unlink()
                mid.symlink_to("/etc/passwd")
                self.assertEqual(helper.inspect_path(
                    fd, "etc/machine-id", want_machine_id=True)["state"],
                    "SYMLINK_NOT_FOLLOWED")
            finally:
                os.close(fd)

    def test_no_private_ssh_host_key_data_ever_returned(self):
        with tempfile.TemporaryDirectory() as root:
            sshdir = Path(root) / "etc/ssh"
            sshdir.mkdir(parents=True)
            (sshdir / "ssh_host_rsa_key").write_text("FAKE_SECRET_DO_NOT_DISCLOSE")
            (sshdir / "ssh_host_rsa_key.pub").write_text("public")
            (sshdir / "unrelated.conf").write_text("not counted")
            fd = os.open(root, helper.DIR_FLAGS)
            try:
                result = helper.inspect_path(fd, "etc/ssh", ssh_keys=True)
                self.assertEqual(result["ssh_host_private_key_name_count"], 1)
                self.assertEqual(result["ssh_host_public_key_name_count"], 1)
                self.assertNotIn("FAKE_SECRET", str(result))
                self.assertEqual(helper.inspect_path(fd, "var/lib/cloud",
                                                     count_dir=True)["state"],
                                 "ABSENT")
            finally:
                os.close(fd)

    def test_untrusted_symlink_in_fixed_parent_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "etc").symlink_to("/etc")
            fd = os.open(root, helper.DIR_FLAGS)
            try:
                with self.assertRaises(helper.Refused):
                    helper.inspect_path(fd, "etc/machine-id", want_machine_id=True)
            finally:
                os.close(fd)

    def test_helper_does_not_write_or_return_unbounded_entries(self):
        source = HELPER.read_text()
        for forbidden in ("import subprocess", "from subprocess",
                          "open(path,", "os.remove(", "os.unlink(",
                          "os.rename(", "os.mkdir(", "os.makedirs(",
                          "os.chmod(", "os.chown(", "os.write(",
                          "shutil", "requests", "urllib"):
            self.assertNotIn(forbidden, source)
        for required in ("O_NOATIME", "O_NOFOLLOW", "O_NONBLOCK",
                         "MAX_MACHINE_ID_BYTES = 128",
                         "MAX_DIR_ENTRIES = 1024",
                         "raw_machine_ids_disclosed",
                         "raw_host_key_material_disclosed",
                         "template_sanitation"):
            self.assertIn(required, source)

if __name__ == "__main__":
    unittest.main()
