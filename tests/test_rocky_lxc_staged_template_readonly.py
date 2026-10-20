#!/usr/bin/env python3
"""Static checks of strictly read-only post-transfer Rocky PVE template audit."""
from pathlib import Path
import unittest

import yaml

SOURCE = (Path(__file__).resolve().parents[1] /
          "ansible/playbooks/audit-rocky-9-8-staged-template-readonly.yml")


class StagedRockyTemplateAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()
        cls.play = yaml.safe_load(cls.source)[0]
        cls.tasks = cls.play["tasks"]

    def test_proxmox_scope_without_apply(self):
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertEqual(self.play["vars"]["rocky_expected_bytes"], 107425612)
        self.assertEqual(
            self.play["vars"]["rocky_expected_sha256"],
            "1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5",
        )

    def test_no_unreviewed_mutation_modules_or_commands(self):
        allowed = {
            "ansible.builtin.command",
            "ansible.builtin.stat",
            "ansible.builtin.assert",
            "ansible.builtin.debug",
        }
        expected_commands = {
            ("hostname", "-s"),
            ("pveversion",),
            ("pvesm", "path"),
            ("pvesm", "status"),
            ("pveam", "list"),
            ("pvesh", "get"),
            ("pct", "config"),
            ("zpool", "status"),
        }
        for task in self.tasks:
            modules = {k for k in task if k.startswith("ansible.builtin.")}
            self.assertTrue(modules <= allowed, msg=task["name"])
            command = task.get("ansible.builtin.command")
            if command:
                self.assertIs(task.get("changed_when"), False, msg=task["name"])
                argv = command["argv"]
                self.assertTrue(
                    any(tuple(argv[:len(prefix)]) == prefix
                        for prefix in expected_commands),
                    msg=task["name"],
                )

    def test_exact_sha_hash_no_symlink_and_no_temp_file(self):
        s = self.source
        for expected in (
            "follow: false",
            "get_checksum: true",
            "checksum_algorithm: sha256",
            "rocky_after_file.stat.size == rocky_expected_bytes",
            "rocky_after_file.stat.checksum == rocky_expected_sha256",
            "rocky_after_file.stat.mode == '0600'",
            "rocky_after_file.stat.nlink == 1",
            "rocky_after_file.stat.pw_name == 'root'",
            "rocky_after_file.stat.gr_name == 'root'",
            "not rocky_after_partial.stat.exists",
        ):
            self.assertIn(expected, s)

    def test_supported_pve_template_lookup(self):
        calls = [t["ansible.builtin.command"]["argv"] for t in self.tasks
                 if "ansible.builtin.command" in t]
        self.assertIn(
            ["pvesm", "path", "{{ rocky_staged_volid }}"], calls,
        )
        self.assertIn(["pveam", "list", "local"], calls)
        self.assertIn("rocky_staged_volid | regex_escape", self.source)
        self.assertIn("rocky_after_resolved_path.stdout | trim == rocky_staged_path",
                      self.source)

    def test_fails_closed_on_vmids_and_ct701(self):
        self.assertIn("[702, 790, 791]", self.source)
        self.assertIn("not rocky_after_ct790_config.stat.exists", self.source)
        self.assertIn("not rocky_after_vm790_config.stat.exists", self.source)
        self.assertIn("not (rocky_after_ct701.stdout is search", self.source)
        for marker in (
            "pct_create_authorized: false",
            "new_guest_created: false",
            "network_egress_authorized: false",
            "archive_extracted: false",
        ):
            self.assertIn(marker, self.source)


if __name__ == "__main__":
    unittest.main()
