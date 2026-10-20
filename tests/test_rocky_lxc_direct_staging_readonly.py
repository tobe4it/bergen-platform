#!/usr/bin/env python3
"""Static no-write and explicit approval-boundary regression tests."""
from pathlib import Path
import unittest
import yaml

PLAYBOOK = (Path(__file__).resolve().parents[1] /
            "ansible/playbooks/audit-rocky-9-8-direct-import-staging-readonly.yml")


class DirectRockyTemplateStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLAYBOOK.read_text()
        cls.plays = yaml.safe_load(cls.source)

    def test_exact_controller_and_pve_separation(self):
        self.assertEqual(len(self.plays), 2)
        controller, host = self.plays
        self.assertEqual(controller["hosts"], "bp-controller")
        self.assertEqual(controller["connection"], "local")
        self.assertIs(controller["become"], False)
        self.assertEqual(host["hosts"], "venombox")
        self.assertIs(host["become"], True)
        self.assertIs(controller["gather_facts"], False)
        self.assertIs(host["gather_facts"], False)

    def test_no_write_modules_or_undocumented_shell_execution(self):
        forbidden = {
            "ansible.builtin.shell", "ansible.builtin.raw",
            "ansible.builtin.script", "ansible.builtin.copy",
            "ansible.builtin.template", "ansible.builtin.file",
            "ansible.builtin.fetch", "ansible.builtin.synchronize",
            "ansible.builtin.apt", "ansible.builtin.dnf",
            "ansible.builtin.systemd", "ansible.builtin.service",
        }
        for play in self.plays:
            for task in play["tasks"]:
                self.assertFalse(forbidden.intersection(task),
                                 msg=task["name"])
                self.assertNotIn("ansible.builtin.uri", task)
                cmd = task.get("ansible.builtin.command")
                if cmd:
                    self.assertIs(task.get("changed_when"), False)
                    args = cmd.get("argv", [])
                    self.assertNotIn(args[:2], [
                        ["pct", "create"], ["pct", "set"], ["pct", "start"],
                        ["pct", "stop"], ["pct", "destroy"], ["pct", "push"],
                        ["pveam", "download"], ["pvesm", "alloc"],
                    ])

    def test_pinned_source_and_local_template_scope(self):
        self.assertIn("1fd0ade221871319d5ae7bed9ece57c001d79ef950c1263814d5b8d48779b7e5",
                      self.source)
        self.assertIn("ROCKY_LXC_ROOTFS_STRUCTURAL_AUDIT_PASS",
                      self.source)
        self.assertIn("archive_extracted", self.source)
        self.assertIn("pinned_missing_link_exception_count", self.source)
        self.assertIn("privileged_mode_regular_count", self.source)
        self.assertIn("rockylinux-9.8-lxc_20261018_amd64.tar.xz",
                      self.source)
        self.assertIn("not rocky_direct_target_file.stat.exists",
                      self.source)

    def test_pve_storage_api_and_strict_local_template_validation(self):
        tasks = self.plays[1]["tasks"]
        queries = [
            t for t in tasks
            if t.get("ansible.builtin.command", {}).get("argv") ==
            ["pvesh", "get", "/storage", "--output-format", "json"]
        ]
        self.assertEqual(len(queries), 1)
        self.assertIs(queries[0].get("changed_when"), False)
        self.assertNotIn("pvesm, config, local", self.source)
        self.assertIn("selectattr('storage', 'equalto', 'local')", self.source)
        self.assertIn("rocky_local_storage.type == 'dir'", self.source)
        self.assertIn("rocky_local_storage.path == '/var/lib/vz'", self.source)
        self.assertIn("'vztmpl' in rocky_local_storage.content.split(',')",
                      self.source)
        self.assertIn("rocky_local_storage.disable | default(false) | bool",
                      self.source)
        self.assertIn("'venombox' in rocky_local_storage.nodes.split(',')",
                      self.source)

    def test_no_template_or_guest_import_is_authorized(self):
        self.assertEqual(self.plays[1]["vars"]["rocky_target_vmid"], 790)
        self.assertEqual(self.plays[1]["vars"]["rocky_future_runtime_vmid"], 791)
        self.assertEqual(self.plays[1]["vars"]["rocky_future_restore_vmid"], 702)
        for gate in ("template_staging_apply_authorized: false",
                     "pct_create_authorized: false",
                     "network_egress_authorized: false",
                     "new_guest_created: false",
                     "source_archive_transferred: false"):
            self.assertIn(gate, self.source)
        self.assertIn("hostvars['bp-controller'].rocky_direct_source_audit is defined", self.source)
        self.assertIn("rocky_direct_701_config", self.source)
        self.assertIn("local-zfs", self.source)
        self.assertIn("zpool, status, -x", self.source)


if __name__ == "__main__":
    unittest.main()
