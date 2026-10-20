#!/usr/bin/env python3
"""CT790 creation plan is no-write by default and doubly approval gated."""
from pathlib import Path
import unittest
import yaml

PATH = (Path(__file__).resolve().parents[1] /
        "ansible/playbooks/create-rocky-9-8-ct790-offline.yml")


class RockyCt790CreatePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[1]
        cls.tasks = cls.play["tasks"]

    def test_readonly_preflight_is_mandatory(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-create-readonly.yml"
        })
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertEqual(self.play["vars"]["rocky_create_vmid"], 790)
        self.assertEqual(self.play["vars"]["rocky_create_rootfs"], "local-zfs:16")

    def test_one_pinned_pct_create_only(self):
        creates = [t for t in self.tasks
                   if t.get("ansible.builtin.command", {}).get("argv", [])[:2]
                   == ["pct", "create"]]
        self.assertEqual(len(creates), 1)
        task = creates[0]
        self.assertEqual(task["when"], "rocky_create_apply | bool")
        self.assertIs(task["no_log"], True)
        args = task["ansible.builtin.command"]["argv"]
        self.assertEqual(args[:4], [
            "pct", "create", "790",
            "local:vztmpl/rockylinux-9.8-lxc_20261018_amd64.tar.xz"
        ])
        self.assertNotIn("--net0", args)
        self.assertNotIn("--net1", args)
        for option, value in (
            ("--hostname", "rocky9-base-790"),
            ("--ostype", "centos"),
            ("--rootfs", "local-zfs:16"),
            ("--cores", "2"),
            ("--memory", "2048"),
            ("--swap", "0"),
            ("--unprivileged", "1"),
            ("--onboot", "0"),
            ("--features", "nesting=0"),
            ("--start", "0"),
            ("--protection", "1"),
        ):
            self.assertEqual(args[args.index(option)+1], value)

    def test_no_other_write_operation_and_bounded_identities(self):
        for task in self.tasks:
            self.assertFalse({
                "ansible.builtin.shell", "ansible.builtin.raw",
                "ansible.builtin.script", "ansible.builtin.copy",
                "ansible.builtin.file", "ansible.builtin.template",
                "ansible.builtin.systemd", "ansible.builtin.apt",
                "ansible.builtin.dnf"
            }.intersection(task), task["name"])
            argv = task.get("ansible.builtin.command", {}).get("argv", [])
            if argv[:2] != ["pct", "create"] and argv:
                self.assertEqual(argv[:2], ["pct", "config"] if argv[1] == "config"
                                 else ["pct", "status"])
                self.assertIn(argv[2], ("790", "701"))
                self.assertIs(task.get("changed_when"), False)
        for required in (
            "rocky_after_file.stat.checksum ==",
            "not rocky_after_ct790_config.stat.exists",
            "not rocky_after_vm790_config.stat.exists",
            "hostvars['bp-controller'].rocky_ct790_ownership is defined",
            "default_idmap_compatibility",
            "rocky_ct790_subid.stdout",
            "ct701_unchanged: true",
            "network_egress_authorized: false",
            "template_converted: false",
        ):
            self.assertIn(required, self.source)

    def test_apply_requires_exact_confirmation_and_never_implicitly_authorized(self):
        self.assertIn("rocky_ct790_create_apply | default(false) | bool", self.source)
        self.assertIn("CREATE_ONLY_OFFLINE_ROCKY_9_8_CT790", self.source)
        self.assertIn("rocky_ct790_create_confirm == rocky_create_exact_approval",
                      self.source)
        self.assertIn("rocky_ct790_create_apply is defined", self.source)
        self.assertIn("rocky_ct790_create_confirm is defined", self.source)
        for task in self.tasks:
            if task["name"].startswith(("Create only explicitly", "Inspect CT790",
                                        "Fail closed unless", "Confirm original",
                                        "Refuse any deviation", "Report bounded")):
                self.assertEqual(task.get("when"), "rocky_create_apply | bool")
        readonly_tasks = [
            t for t in self.tasks if
            "ROCKY_9_8_CT790_CREATE_PLAN_READ_ONLY_READY" in str(t)
        ]
        self.assertEqual(len(readonly_tasks), 1)
        self.assertEqual(readonly_tasks[0]["when"], "not rocky_create_apply | bool")

if __name__ == "__main__":
    unittest.main()
