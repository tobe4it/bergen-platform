#!/usr/bin/env python3
"""Read-only CT790 first-boot identity and SSH unit metadata safeguards."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "ansible/files/nextcloud/audit_ct790_firstboot_identity_units.py"
PLAY = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-firstboot-identity-units-readonly.yml"
spec = importlib.util.spec_from_file_location("ct790_identity_units", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

class StoppedIdentityUnitAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PLAY.read_text()
        cls.plays = yaml.safe_load(cls.raw)
        cls.tasks = cls.plays[1]["tasks"]

    def test_uses_existing_no_write_stopped_only_rootfs_audit(self):
        self.assertEqual(len(self.plays), 2)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-ct790-postshutdown-sanitization-readonly.yml"
        })
        self.assertEqual(self.plays[1]["hosts"], "venombox")
        self.assertTrue(self.plays[1]["become"])
        self.assertFalse(self.plays[1]["gather_facts"])
        self.assertTrue(self.plays[1]["any_errors_fatal"])
        for required in (
            "'status: stopped' in rocky_post_state.stdout_lines",
            "'status: stopped' in rocky_sanitation_after_status.stdout_lines",
            "rocky_sanitation_mounted.stdout | trim == 'yes'",
            "rocky_sanitation_findmnt.stdout == rocky_release_findmnt.stdout",
            "'status: stopped' in rocky_identity_after_status.stdout_lines",
            "rocky_identity_ct701_after.stdout == rocky_post_ct701.stdout",
            "audit_ct790_firstboot_identity_units.py",
            "ROCKY_9_8_CT790_FIRSTBOOT_IDENTITY_UNITS_READ_ONLY_RECORDED",
            "authoritative_firstboot_generation_proven: false",
        ):
            self.assertIn(required, self.raw)

    def test_review_tasks_are_only_no_mutation_modules(self):
        cmds = []
        for task in self.tasks:
            modules = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1, task["name"])
            self.assertIn(modules[0], ("ansible.builtin.command",
                                      "ansible.builtin.assert",
                                      "ansible.builtin.debug"), task["name"])
            if "ansible.builtin.command" not in task:
                continue
            c = task["ansible.builtin.command"]["argv"]
            cmds.append(c)
            self.assertIs(task.get("changed_when"), False)
            self.assertTrue(
                c in (["pct", "status", "790"], ["pct", "config", "701"]) or
                c[:2] == ["python3", "-c"], task["name"])
            if c[:2] == ["python3", "-c"] or c == ["pct", "config", "701"]:
                self.assertTrue(task.get("no_log"))
        self.assertEqual(len(cmds), 4)
        self.assertEqual(sum(c == ["pct", "status", "790"] for c in cmds), 2)
        for forbidden in ("ansible.builtin.shell:", "ansible.builtin.raw:",
                          "ansible.builtin.copy:", "ansible.builtin.file:",
                          "ansible.builtin.template:", "ansible.builtin.mount:",
                          "ansible.builtin.service:", "ansible.builtin.systemd:",
                          "argv: [pct, start", "argv: [pct, mount",
                          "argv: [pct, template", "argv: [zfs, mount"):
            self.assertNotIn(forbidden, self.raw)

    def test_safe_regular_unit_parsing_never_returns_original_text(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root, "usr/lib/systemd/system")
            folder.mkdir(parents=True)
            unit = folder / "sshd-keygen@.service"
            unit.write_text(
                "[Unit]\nConditionPathExists=!/etc/ssh/ssh_host_%i_key\n"
                "[Service]\nExecStart=/usr/libexec/openssh/sshd-keygen %i\n"
                "# PrivateMarker secret string must not be returned\n"
            )
            fd = os.open(root, helper.DIR_FLAGS)
            try:
                d = helper.fixed_path(fd, "usr/lib/systemd/system/sshd-keygen@.service",
                                      parse_unit=True)
                self.assertEqual(d["state"], "REGULAR_UNIT_PRESENT")
                self.assertTrue(d["ssh_keygen_helper_executed"])
                self.assertTrue(d["key_absence_condition_declared"])
                self.assertNotIn("PrivateMarker", str(d))
                unit.unlink()
                unit.symlink_to("/etc/shadow")
                self.assertEqual(helper.fixed_path(
                    fd, "usr/lib/systemd/system/sshd-keygen@.service",
                    parse_unit=True)["state"], "SYMLINK_PRESENT_TARGET_UNREAD")
            finally:
                os.close(fd)

    def test_only_fixed_safe_paths_no_links_followed_or_writes(self):
        s = HELPER.read_text()
        for snippet in ("O_NOATIME", "O_NOFOLLOW", "O_NONBLOCK",
                        "MAX_FILE_BYTES = 16384", "MAX_DIR_ENTRIES = 128",
                        "raw_unit_text_or_secrets_disclosed",
                        "firstboot_regeneration_proven"):
            self.assertIn(snippet, s)
        for forbidden in ("import subprocess", "from subprocess",
                          "subprocess.", "os.readlink(", "os.remove(",
                          "os.unlink(", "os.write(", "os.rename(",
                          "os.chmod(", "os.chown(", "os.mkdir(",
                          "os.makedirs(", "shutil", "requests"):
            self.assertNotIn(forbidden, s)

    def test_does_not_prove_clone_regeneration_without_actual_clone(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "etc").mkdir()
            fd = os.open(root, helper.DIR_FLAGS)
            try:
                self.assertEqual(helper.fixed_path(
                    fd, "etc/systemd/system/multi-user.target.wants/sshd.service"
                )["state"], "ABSENT")
                self.assertEqual(helper.fixed_path(
                    fd, "usr/lib/systemd/system/sshd.service", parse_unit=True
                )["state"], "ABSENT")
            finally:
                os.close(fd)
        self.assertIn("authoritative_firstboot_generation_proven: false",
                      self.raw)

if __name__ == "__main__":
    unittest.main()
