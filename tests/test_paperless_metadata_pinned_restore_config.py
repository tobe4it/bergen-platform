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

    def test_archived_lxc_classification_only_emits_fixed_families(self):
        config = (SAMPLE
                  + "lxc.apparmor.profile: hidden-sensitive-configuration\n"
                  + "lxc.cgroup2.devices.allow: hidden-device\n"
                  + "lxc.mount.entry: hidden-private-path\n")
        with self.assertRaises(self.blocked) as caught:
            self.sanitize(config)
        self.assertEqual(str(caught.exception),
                         "ARCHIVED_LXC_OVERRIDE_PRESENT")
        self.assertEqual(caught.exception.lxc_count, 3)
        self.assertEqual(
            caught.exception.lxc_classes,
            ("APPARMOR_OVERRIDE", "CGROUP_DEVICE_OVERRIDE", "MOUNT_OVERRIDE"))
        self.assertNotIn("hidden-", str(caught.exception))
        self.assertNotIn("hidden-", repr(caught.exception.lxc_classes))

    def test_unknown_lxc_override_is_classified_but_still_blocked(self):
        with self.assertRaises(self.blocked) as caught:
            self.sanitize(SAMPLE + "lxc.init.cmd: do-not-leak\n")
        self.assertEqual(caught.exception.lxc_classes,
                         ("OTHER_LXC_OVERRIDE",))
        self.assertEqual(caught.exception.lxc_count, 1)
        self.assertEqual(str(caught.exception),
                         "ARCHIVED_LXC_OVERRIDE_PRESENT")

    def test_lxc_diag_rejects_large_key_scope_without_values(self):
        bulk = "".join("lxc.opaque%d: secret\n" % k for k in range(33))
        with self.assertRaises(self.blocked) as caught:
            self.sanitize(SAMPLE + bulk)
        self.assertEqual(str(caught.exception),
                         "ARCHIVED_LXC_OVERRIDE_SCOPE_UNREVIEWED")

    def test_exact_fuse_pair_is_identified_but_restore_stays_blocked(self):
        variants = (
            "/dev/fuse dev/fuse none bind,create=file",
            "/dev/fuse dev/fuse none bind,optional,create=file",
            "/dev/fuse dev/fuse none bind,create=file,optional 0 0",
        )
        for value in variants:
            with self.subTest(pattern=value):
                raw = (SAMPLE
                       + "lxc.cgroup2.devices.allow: c 10:229 rwm\\n"
                       + "lxc.mount.entry: " + value + "\\n")
                with self.assertRaises(self.blocked) as caught:
                    self.sanitize(raw)
                refusal = caught.exception
                self.assertEqual(str(refusal),
                                 "ARCHIVED_LXC_OVERRIDE_PRESENT")
                self.assertEqual(refusal.lxc_count, 2)
                self.assertEqual(refusal.cgroup_profile,
                                 "EXACT_FUSE_DEVICE_10_229")
                self.assertEqual(refusal.mount_profile,
                                 "EXACT_FUSE_DEVICE_BIND")
                self.assertEqual(refusal.fuse_pair,
                                 "MATCHES_KNOWN_FUSE_PATTERN")

    def test_non_fuse_override_must_not_be_called_fuse(self):
        raw = (SAMPLE
               + "lxc.cgroup2.devices.allow: c 10:200 rwm\\n"
               + "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file\\n")
        with self.assertRaises(self.blocked) as caught:
            self.sanitize(raw)
        refusal = caught.exception
        self.assertEqual(str(refusal), "ARCHIVED_LXC_OVERRIDE_PRESENT")
        self.assertEqual(refusal.cgroup_profile,
                         "OTHER_OR_MISSING_CGROUP_RULE")
        self.assertEqual(refusal.mount_profile,
                         "OTHER_OR_MISSING_MOUNT_RULE")
        self.assertEqual(refusal.fuse_pair, "NOT_PROVEN")
        self.assertNotIn("/dev/net/tun", repr(refusal.fuse_pair))

    def test_fuse_pair_is_not_proven_if_extra_rule_exists(self):
        raw = (SAMPLE
               + "lxc.cgroup2.devices.allow: c 10:229 rwm\\n"
               + "lxc.mount.entry: /dev/fuse dev/fuse none bind,create=file\\n"
               + "lxc.cap.keep: sys_admin\\n")
        with self.assertRaises(self.blocked) as caught:
            self.sanitize(raw)
        refusal = caught.exception
        self.assertEqual(refusal.cgroup_profile,
                         "EXACT_FUSE_DEVICE_10_229")
        self.assertEqual(refusal.mount_profile,
                         "EXACT_FUSE_DEVICE_BIND")
        self.assertEqual(refusal.fuse_pair, "NOT_PROVEN")

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
        self.assertIn("ARCHIVED_LXC_OVERRIDE_REMAINS_BLOCKED=YES", content)
        self.assertIn("bp_pinned_allowed_lxc_classes", content)
        self.assertIn("ARCHIVED_LXC_OVERRIDE_CLASSIFICATION_INVALID", content)
        self.assertIn("FUSE_PAIR_PROFILE", content)
        self.assertIn("MATCHES_KNOWN_FUSE_PATTERN", content)
        self.assertIn("ARCHIVED_LXC_OVERRIDE_REMAINS_BLOCKED=YES", content)

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
