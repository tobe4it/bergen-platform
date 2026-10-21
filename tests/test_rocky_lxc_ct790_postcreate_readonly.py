#!/usr/bin/env python3
"""Prevent accidental mutation or overstated claims in post-create CT790 audit."""
from pathlib import Path
import unittest
import yaml

PATH = (Path(__file__).resolve().parents[1] /
        "ansible/playbooks/audit-rocky-9-8-ct790-postcreate-readonly.yml")


class Ct790PostCreateReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[0]
        cls.tasks = cls.play["tasks"]

    def test_exact_single_pve_host_and_unconditionally_readonly(self):
        self.assertEqual(len(self.plays), 1)
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertEqual(self.play["vars"]["rocky_post_vmid"], 790)
        self.assertEqual(
            self.play["vars"]["rocky_post_sha256"],
            "1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5"
        )
        self.assertNotIn("import_playbook", self.source)

    def test_allowlist_all_task_types_and_commands(self):
        allowed = {
            "ansible.builtin.assert",
            "ansible.builtin.stat",
            "ansible.builtin.command",
            "ansible.builtin.set_fact",
            "ansible.builtin.debug",
        }
        expected_prefixes = (
            ["hostname", "-s"], ["pveversion"],
            ["pct", "config"], ["pct", "status"],
            ["pvesh", "get"], ["pvesm", "path"], ["pvesm", "list"],
            ["zfs", "list"], ["zpool", "status"],
        )
        for task in self.tasks:
            modules = {k for k in task if k.startswith("ansible.builtin.")}
            self.assertEqual(len(modules), 1, msg=task["name"])
            self.assertTrue(modules <= allowed, msg=task["name"])
            argv = task.get("ansible.builtin.command", {}).get("argv")
            if argv is not None:
                self.assertIs(task.get("changed_when"), False, msg=task["name"])
                self.assertTrue(
                    any(argv[:len(prefix)] == prefix for prefix in expected_prefixes),
                    msg=task["name"],
                )
            if "ansible.builtin.set_fact" in task:
                self.assertIs(task.get("changed_when"), False)
        for forbidden in (
            "pct, start", "pct, create", "pct, mount",
            "pct, template", "pct, exec", "pct, set",
            "pct, shutdown", "pct, destroy",
            "zfs, mount", "zfs, set", "zfs, destroy",
            "ansible.builtin.copy", "ansible.builtin.shell",
            "ansible.builtin.raw", "ansible.builtin.file",
            "ansible.builtin.template", "ansible.builtin.systemd",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_exact_ct_and_protection_invariants(self):
        for expected in (
            "rocky_post_host.stdout == 'venombox'",
            "rocky_post_vmid == 790",
            "'hostname: rocky9-base-790'",
            "'ostype: centos'",
            "'cores: 2'",
            "'memory: 2048'",
            "'swap: 0'",
            "'unprivileged: 1'",
            "'onboot: 0'",
            "'protection: 1'",
            "'status: stopped'",
            "rootfs: local-zfs:subvol-790-disk-[0-9]+,size=16G",
            "'template: 1' not in rocky_post_config.stdout_lines",
            "not (rocky_post_ct701.stdout is",
            "selectattr('vmid', 'equalto', 790)",
            "selectattr('vmid', 'in', [702, 791])",
        ):
            self.assertIn(expected, self.source)

    def test_exact_pvesm_zfs_and_sha256_checks(self):
        for expected in (
            "get_checksum: true",
            "checksum_algorithm: sha256",
            "rocky_post_template_file.stat.mode == '0600'",
            "rocky_post_template_file.stat.checksum == rocky_post_sha256",
            "[pvesm, path, \"{{ rocky_post_rootfs_volid }}\"]",
            "[pvesm, list, local-zfs, --vmid, '790']",
            "rocky_post_rootfs_volid is match(",
            "rocky_post_zfs_storage.type == 'zfspool'",
            "rocky_post_zfs_columns[0] == rocky_post_dataset",
            "rocky_post_zfs_columns[1] == 'filesystem'",
            "rocky_post_zfs_columns[2] == rocky_post_rootfs_path.stdout | trim",
        ):
            self.assertIn(expected, self.source)

    def test_status_is_metadata_only_and_closes_future_gates(self):
        for expected in (
            "ROCKY_9_8_CT790_POSTCREATE_READ_ONLY_VERIFIED",
            "rootfs_contents_independently_read: false",
            "os_release_inside_new_rootfs_verified: false",
            "runtime_compatibility_tested: false",
            "pct_start_authorized: false",
            "pct_template_authorized: false",
        ):
            self.assertIn(expected, self.source)


if __name__ == "__main__":
    unittest.main()
