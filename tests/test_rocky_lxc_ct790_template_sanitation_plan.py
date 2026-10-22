#!/usr/bin/env python3
"""CT790 template sanitation proposal is strictly no-write and stopped-only."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ansible/playbooks/plan-rocky-9-8-ct790-template-sanitization-readonly.yml"


class TemplateSanitationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PATH.read_text()
        cls.plays = yaml.safe_load(cls.raw)
        cls.play = cls.plays[1]
        cls.tasks = cls.play["tasks"]

    def test_stopped_rootfs_proven_by_existing_independent_audit(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-postshutdown-sanitization-readonly.yml",
        })
        self.assertEqual(self.play["hosts"], "venombox")
        self.assertIs(self.play["become"], True)
        self.assertIs(self.play["gather_facts"], False)
        self.assertIs(self.play["any_errors_fatal"], True)
        self.assertIs(self.play["vars"]["rocky_sanitation_apply_authorized"], False)
        self.assertIs(self.play["vars"]["rocky_template_conversion_authorized"], False)
        for required in (
            "'status: stopped' in rocky_sanitation_after_status.stdout_lines",
            "'status: stopped' in rocky_post_state.stdout_lines",
            "rocky_sanitation_mounted.stdout | trim == 'yes'",
            "rocky_sanitation_findmnt.stdout == rocky_release_findmnt.stdout",
            "rocky_sanitation_ct701_config_after.stdout == rocky_post_ct701.stdout",
            "'protection: 1' in rocky_post_config.stdout_lines",
            "'unprivileged: 1' in rocky_post_config.stdout_lines",
            "ROCKY_9_8_CT790_TEMPLATE_SANITATION_PLAN_READ_ONLY_READY",
        ):
            self.assertIn(required, self.raw)

    def test_exact_evidence_regression_from_operator_audit(self):
        for required in (
            "rocky_sanitation_categories | length == 12",
            "rocky_sanitation_categories.etc_machine_id.state == 'SET_32HEX'",
            "rocky_sanitation_categories.dbus_machine_id.state == 'ABSENT'",
            "rocky_sanitation_categories.ssh_host_keys.ssh_host_private_key_name_count == 3",
            "rocky_sanitation_categories.ssh_host_keys.ssh_host_public_key_name_count == 3",
            "rocky_sanitation_categories.systemd_random_seed.size_nonzero",
            "rocky_sanitation_categories.dnf_package_cache.top_level_entries == 8",
            "rocky_sanitation_categories.dnf_runtime_state.top_level_entries == 4",
            "rocky_sanitation_categories.network_manager_runtime.top_level_entries == 4",
            "rocky_sanitation_categories.network_manager_connections.top_level_entries == 0",
            "rocky_sanitation_categories.systemd_timers_state.top_level_entries == 1",
            "cloud_init_state_action: REVIEW_INVENTORY_CATEGORY_BEFORE_DECISION",
        ):
            self.assertIn(required, self.raw)

    def test_only_assert_and_debug_no_commands_or_mutations(self):
        self.assertEqual(len(self.tasks), 3)
        assert_count = 0
        for task in self.tasks:
            modules = [key for key in task if key.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, task["name"])
            self.assertIn(modules[0], ("ansible.builtin.assert", "ansible.builtin.debug"))
            assert_count += modules[0] == "ansible.builtin.assert"
        self.assertEqual(assert_count, 2)
        for forbidden in (
            "ansible.builtin.command:", "ansible.builtin.shell:",
            "ansible.builtin.raw:", "ansible.builtin.file:",
            "ansible.builtin.copy:", "ansible.builtin.stat:",
            "ansible.builtin.systemd:", "ansible.builtin.template:",
            "ansible.builtin.package:", "ansible.builtin.mount:",
            "ansible.builtin.lineinfile:", "ansible.builtin.replace:",
            "pct, start", "pct, mount", "pct, shutdown",
            "pct, template", "zfs, mount",
        ):
            self.assertNotIn(forbidden, self.raw)
        for proof in (
            "rootfs_sanitation_complete: false",
            "cleanup_executed: false",
            "files_written: 0",
            "guest_started: false",
            "new_mount_created: false",
            "pct_template_authorized: false",
            "apply_authorized: false",
            "KEEP_INTACT_FOR_NETWORKED_CLONES_UNLESS_SEPARATELY_APPROVED",
            "PREFER_EMPTY_MACHINE_ID_FOR_UNIQUE_CLONE_ID_WITHOUT_FIRSTBOOT_AFTER_CLONE_TEST",
            "INVESTIGATE_CONTENTS_DO_NOT_DELETE_DIRECTORY",
            "REMOVE_EXACT_VERIFIED_HOST_KEY_PAIRS_ONLY_AFTER_CONFIRMING_NO_SSHD_AND_OPTIONAL_CLONE_PROVISIONING",
        ):
            self.assertIn(proof, self.raw)

if __name__ == "__main__":
    unittest.main()
