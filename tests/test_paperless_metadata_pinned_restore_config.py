"""Offline-only test for pinned LXC archive configuration safety review.

No Proxmox, NFS, shell commands, archive reads or guest changes.
"""
import ast
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_pinned_archive_restore_config.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-metadata-pinned-restore-config.yml"

SAMPLE = (
    "arch: amd64\n"
    "hostname: bergen-paperless\n"
    "unprivileged: 1\n"
    "rootfs: local-zfs:subvol-126-disk-0,size=32G\n"
    "mp0: local-zfs:subvol-126-disk-1,mp=/srv/bergen-paperless,"
    "backup=1,size=100G\n"
    "net0: name=eth0,bridge=vmbr0,ip=dhcp,type=veth\n"
    "onboot: 1\n"
    "features: nesting=1\n"
)


class PinnedRestoreConfigSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text()
        cls.tree = ast.parse(cls.source)
        selected = []
        # Execute only the production regex constants needed by the extracted
        # sanitizer. The previous fixture omitted them, causing NameError
        # rather than testing valid/invalid archived configurations.
        for n in cls.tree.body:
            if isinstance(n, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in {"ROOTFS", "MP0"}
                for target in n.targets
            ):
                selected.append(n)
            if isinstance(n, ast.ClassDef) and n.name == "Refuse":
                selected.append(n)
            if isinstance(n, ast.FunctionDef) and n.name in (
                    "require", "sanitized_config"):
                selected.append(n)
        scope = {"re": re}
        exec(compile(ast.Module(body=selected, type_ignores=[]),
                     "<pinned-pve-archive-review>", "exec"), scope)
        cls.sanitize = staticmethod(scope["sanitized_config"])
        cls.blocked = scope["Refuse"]

    def test_expected_backup_network_is_detected_not_inherited(self):
        result = self.sanitize(SAMPLE)
        self.assertEqual(result["ARCHIVED_UNPRIVILEGED"], "YES")
        self.assertEqual(result["ARCHIVED_NET_INTERFACE_COUNT"], 1)
        self.assertTrue(result["ARCHIVED_ONBOOT_ENABLED"])
        self.assertEqual(result["ARCHIVED_EXTRA_MOUNTS"], 0)
        self.assertIn("NO_NETWORK", result["REQUIRED_RESTORE_OVERRIDE"])

    def test_unprivileged_is_mandatory(self):
        with self.assertRaises(self.blocked):
            self.sanitize(SAMPLE.replace("unprivileged: 1",
                                         "unprivileged: 0"))

    def test_identity_refusals_identify_only_fixed_policy_categories(self):
        # No raw hostname, archived override key or value is included.
        cases = (
            (SAMPLE.replace("hostname: bergen-paperless",
                            "hostname: opaque-another-guest"),
             "ARCHIVED_HOSTNAME_UNREVIEWED"),
            (SAMPLE.replace("unprivileged: 1", "unprivileged: 0"),
             "ARCHIVED_UNPRIVILEGED_UNREVIEWED"),
            (SAMPLE + "lxc.cgroup2.devices.allow: a\n",
             "ARCHIVED_LXC_OVERRIDE_PRESENT"),
            (SAMPLE.replace("onboot: 1", "onboot: unexpected"),
             "ARCHIVED_ONBOOT_UNREVIEWED"),
        )
        for candidate, expected_code in cases:
            with self.subTest(reason=expected_code):
                with self.assertRaises(self.blocked) as caught:
                    self.sanitize(candidate)
                self.assertEqual(str(caught.exception), expected_code)
                self.assertNotIn("opaque-another-guest", str(caught.exception))
                self.assertNotIn("lxc.cgroup2", str(caught.exception))

    def test_identity_refusal_allowlist_stays_explicit_and_private(self):
        content = PLAY.read_text()
        for code in (
            "ARCHIVED_HOSTNAME_UNREVIEWED",
            "ARCHIVED_UNPRIVILEGED_UNREVIEWED",
            "ARCHIVED_LXC_OVERRIDE_PRESENT",
            "ARCHIVED_ONBOOT_UNREVIEWED",
        ):
            self.assertIn(code, content)
        self.assertNotIn("bp_pinned_config_raw.stdout |", content)

    def test_unreviewed_additional_mount_is_rejected(self):
        with self.assertRaises(self.blocked):
            self.sanitize(SAMPLE + "mp1: /mnt/backup,mp=/data\n")

    def test_host_hook_and_lxc_override_are_rejected(self):
        with self.assertRaises(self.blocked):
            self.sanitize(SAMPLE + "hookscript: local:snippets/a.sh\n")
        with self.assertRaises(self.blocked):
            self.sanitize(SAMPLE + "lxc.apparmor.profile: unconfined\n")

    def test_duplicate_config_keys_are_rejected(self):
        with self.assertRaises(self.blocked):
            self.sanitize(SAMPLE + "net0: name=eth0,bridge=vmbr1\n")

    def test_data_mount_must_be_backup_included(self):
        with self.assertRaises(self.blocked):
            self.sanitize(SAMPLE.replace("backup=1", "backup=0"))

    def test_script_pins_exact_prior_sha_and_reads_only_config(self):
        self.assertIn(
            "7f0ad64c2c7bc3bdca53be5766fbabc62feadd74025e811e52712e78b8bee24f",
            self.source)
        self.assertIn('["pvesm","extractconfig",volid]', self.source)
        self.assertIn('["pvesm","path",volid]', self.source)
        self.assertIn("BACKUP_CHANGED_DURING_CONFIG_READ", self.source)
        self.assertIn("ARCHIVE_FINGERPRINT_DRIFT", self.source)
        for forbidden in (
            '"pct","restore"', '"pct","start"', '"pct","set"',
            "rm -rf", "write_text(", "os.unlink(", "os.remove(",
            "shell=True", "subprocess.Popen(",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_playbook_never_writes_or_exposes_unsanitized_config(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIn("PINNED_ARCHIVE_CONFIG_REQUIRES_READ_ONLY",
                      PLAY.read_text())
        for task in play["tasks"]:
            for forbidden in ("ansible.builtin.copy",
                              "ansible.builtin.systemd_service",
                              "ansible.builtin.file",
                              "ansible.builtin.template",
                              "ansible.builtin.shell"):
                self.assertNotIn(forbidden, task)


if __name__ == "__main__":
    unittest.main()
