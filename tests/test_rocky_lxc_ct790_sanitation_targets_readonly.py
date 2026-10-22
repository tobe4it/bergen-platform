#!/usr/bin/env python3
"""Stopped CT790 exact sanitation candidate discovery safety regressions."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/nextcloud/audit_ct790_sanitation_targets.py"
PLAY = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-sanitization-targets-readonly.yml"
spec = importlib.util.spec_from_file_location("ct790_sanitation_targets", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

class ExactSanitationReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = HELPER.read_text()
        cls.raw = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.raw)
        cls.tasks = cls.plays[1]["tasks"]

    def test_imports_same_run_stopped_zfs_and_firstboot_proof(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-firstboot-identity-units-readonly.yml",
        })
        self.assertEqual(self.plays[1]["hosts"], "venombox")
        self.assertTrue(self.plays[1]["become"])
        self.assertFalse(self.plays[1]["gather_facts"])
        self.assertTrue(self.plays[1]["any_errors_fatal"])
        for text in (
            "rocky_sanitation_findmnt.stdout == rocky_release_findmnt.stdout",
            "rocky_sanitation_mounted.stdout | trim == 'yes'",
            "'status: stopped' in rocky_identity_after_status.stdout_lines",
            "'status: stopped' in rocky_targets_after_status.stdout_lines",
            "rocky_targets_ct701_after.stdout == rocky_post_ct701.stdout",
            "rocky_identity_unit_audit.stdout | from_json",
            "EXACT_SANITATION_TARGETS_READ_ONLY_RECORDED",
            "sanitation_complete: false",
            "sanitation_authorized: false",
            "pct_template_authorized: false",
        ):
            self.assertIn(text, self.raw)

    def test_commands_are_readonly_allowlist(self):
        commands = []
        for task in self.tasks:
            modules = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, task["name"])
            self.assertIn(modules[0], ("ansible.builtin.command",
                                      "ansible.builtin.assert",
                                      "ansible.builtin.debug"))
            if modules[0] == "ansible.builtin.command":
                self.assertIs(task["changed_when"], False)
                argv = task["ansible.builtin.command"]["argv"]
                commands.append(argv)
                self.assertTrue(argv in (["pct", "status", "790"],
                                         ["pct", "config", "701"])
                                or argv[:2] == ["python3", "-c"])
                if argv[:2] == ["python3", "-c"] or argv == ["pct", "config", "701"]:
                    self.assertIs(task.get("no_log"), True)
        self.assertEqual(len(commands), 4)
        for forbidden in (
            "ansible.builtin.shell:", "ansible.builtin.raw:",
            "ansible.builtin.file:", "ansible.builtin.copy:",
            "ansible.builtin.template:", "ansible.builtin.mount:",
            "ansible.builtin.systemd:", "ansible.builtin.dnf:",
            "argv: [pct, start", "argv: [pct, stop",
            "argv: [pct, exec", "argv: [pct, template",
            "argv: [zfs, mount",
        ):
            self.assertNotIn(forbidden, self.raw)

    def test_six_exact_hostkeys_are_metadata_only(self):
        self.assertEqual(len(helper.KEY_TYPES), 3)
        self.assertEqual(len(helper.EXACT_FILES), 9)
        self.assertEqual(len(helper.DIRECTORIES), 5)
        with tempfile.TemporaryDirectory() as root:
            ssh = Path(root, "etc/ssh")
            ssh.mkdir(parents=True)
            for t in helper.KEY_TYPES:
                (ssh / ("ssh_host_" + t + "_key")).write_text("PRIVATE_SENSITIVE_VALUE")
                (ssh / ("ssh_host_" + t + "_key.pub")).write_text("PUBLIC")
            fd = os.open(root, helper.D)
            try:
                for t in helper.KEY_TYPES:
                    meta = helper.target_stat(fd, "etc/ssh/ssh_host_" + t + "_key",
                                              os.stat(root).st_uid)
                    self.assertEqual(meta["state"], "REGULAR_FILE_PRESENT")
                    self.assertTrue(meta["size_nonzero"])
                    self.assertTrue(meta["one_hardlink"])
                    self.assertNotIn("PRIVATE_SENSITIVE_VALUE", str(meta))
                d = helper.fixed_directory(fd, "etc/ssh", tuple(
                    "ssh_host_" + t + "_key" + suffix
                    for t in helper.KEY_TYPES for suffix in ("", ".pub")
                ))
                self.assertEqual(d["expected_key_names_count"], 6)
                self.assertEqual(d["unrecognized_host_key_name_count"], 0)
                (ssh / "ssh_host_dsa_key").write_text("SECRET")
                extra = helper.fixed_directory(fd, "etc/ssh", tuple(
                    "ssh_host_" + t + "_key" + suffix
                    for t in helper.KEY_TYPES for suffix in ("", ".pub")
                ))
                self.assertEqual(extra["unrecognized_host_key_name_count"], 1)
                self.assertNotIn("ssh_host_dsa_key", str(extra))
            finally:
                os.close(fd)

    def test_no_symlink_follow_for_rootfs_paths(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "etc/ssh").mkdir(parents=True)
            target = Path(root, "etc/ssh/ssh_host_ed25519_key")
            target.symlink_to("/etc/shadow")
            fd = os.open(root, helper.D)
            try:
                self.assertEqual(helper.target_stat(
                    fd, "etc/ssh/ssh_host_ed25519_key",
                    os.stat(root).st_uid)["state"], "SYMLINK_NOT_FOLLOWED")
                self.assertEqual(helper.target_stat(fd, "etc/machine-id",
                                                     os.stat(root).st_uid)["state"],
                                 "ABSENT")
            finally:
                os.close(fd)

    def test_bounded_nonmutating_code(self):
        for required in ("O_NOATIME", "O_NOFOLLOW", "MAX_DIR = 1024",
                         "uid_matches_rootfs", "one_hardlink",
                         "ssh_key_contents_read", "arbitrary_names_disclosed",
                         "machine_id_contents_read", "sanitation_authorized"):
            self.assertIn(required, self.script)
        for forbidden in ("import subprocess", "subprocess.", "os.read(",
                          "os.write(", "os.unlink(", "os.remove(",
                          "os.replace(", "os.rename(", "os.mkdir(",
                          "os.makedirs(", "os.chmod(", "os.chown(",
                          "shutil", "requests", "urllib"):
            self.assertNotIn(forbidden, self.script)

if __name__ == "__main__":
    unittest.main()
