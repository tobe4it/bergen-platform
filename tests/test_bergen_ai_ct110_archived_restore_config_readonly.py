"""Archived CT110 configuration audit: read-only, no source-IP disclosure."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_archived_restore_config_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-archived-restore-config-readonly.yml"
spec = importlib.util.spec_from_file_location("ct110_restored_config", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

VOLID = ("bergen-synology-backup:backup/"
         "vzdump-lxc-110-2026_10_20-06_15_00.tar.zst")
SAMPLE = (
    "arch: amd64\n"
    "hostname: bergen-ai\n"
    "rootfs: local-zfs:subvol-110-disk-0,size=36G\n"
    "unprivileged: 1\n"
    "net0: name=eth0,bridge=vmbr0,ip=192.168.0.120/24\n"
    "onboot: 1\n"
    "lxc.mount.entry: /dev/fuse dev/fuse none bind,optional,create=file\n"
)


class ArchivedRestoreConfigTests(TestCase):
    def test_select_one_exact_nonempty_ct110_archive(self):
        with mock.patch.object(a, "run", return_value=(
            '[{"volid":"' + VOLID + '","size":123456}]')):
            self.assertEqual(a.backup_volid(), VOLID)
        for rows in (
            "[]",
            '[{"volid":"' + VOLID + '","size":0}]',
            '[{"volid":"' + VOLID + '","size":1234},{"volid":"' + VOLID + '","size":1234}]',
            '[{"volid":"other:backup/vzdump-lxc-110-2026_10_20-06_15_00.tar.zst","size":1234}]',
            "not json",
        ):
            with self.subTest(rows=rows), mock.patch.object(a, "run", return_value=rows):
                self.assertIsNone(a.backup_volid())

    def test_source_config_profile_is_never_restore_authorization(self):
        values = a.parse_config(SAMPLE)
        self.assertIsNotNone(values)
        report = a.profile(values)
        self.assertEqual(report["STATUS"], "KNOWN_SOURCE_CONFIGURATION")
        self.assertEqual(report["NETWORK_INTERFACE_COUNT"], 1)
        self.assertEqual(report["ONBOOT"], "ENABLED")
        self.assertEqual(report["EXTERNAL_MP_COUNT"], 0)
        self.assertEqual(report["DANGEROUS_CONFIG_DIRECTIVES"], 0)
        self.assertEqual(report["DEVICE_MOUNT_PROFILE"], "EXACT_FUSE_DEVICE_ONLY")
        self.assertNotIn("192.168.", str(report))
        with (mock.patch.object(a, "backup_volid", return_value=VOLID),
              mock.patch.object(a, "run", return_value=SAMPLE)):
            result = a.report()
        self.assertFalse(result["RESTORE_AUTHORIZED"])
        self.assertFalse(result["RESTORE_CONFIG_OVERRIDE_PROVEN"])
        self.assertFalse(result["GUEST_CREATED"])
        self.assertFalse(result["GUEST_STARTED"])
        self.assertEqual(result["NETWORK_ISOLATION"], "NOT_PROVEN")
        self.assertEqual(result["RESTORE_TEST"], "NOT_ATTESTED")
        self.assertNotIn("192.168.", str(result))

    def test_unexpected_mounts_devices_or_bad_keys_fail_closed(self):
        for altered in (
            SAMPLE + "mp0: /data,mp=/private\n",
            SAMPLE + "lxc.mount.entry: /data secret none bind\n",
            SAMPLE.replace("/dev/fuse dev/fuse", "/run/private dev/fuse"),
            SAMPLE + "hookscript: local:snippets/start.sh\n",
            SAMPLE + "lxc.hook.pre-start: /bin/true\n",
            SAMPLE + "dev0: /dev/sda\n",
            SAMPLE.replace("unprivileged: 1", "unprivileged: 0"),
            SAMPLE.replace("local-zfs", "other-storage"),
            SAMPLE + "net1: name=eth1,bridge=vmbr20\n",
            SAMPLE + "net0: name=eth0,bridge=vmbr1\n",
        ):
            with self.subTest(altered=altered), mock.patch.object(
                    a, "run", return_value=altered):
                p = a.profile(a.parse_config(altered))
                self.assertNotEqual(p["STATUS"], "KNOWN_SOURCE_CONFIGURATION")
        missing = SAMPLE.replace("net0: name=eth0,bridge=vmbr0,ip=192.168.0.120/24\n", "")
        self.assertEqual(
            a.profile(a.parse_config(missing))["STATUS"], "REVIEW_REQUIRED")

    def test_config_parser_rejects_non_text_duplicate_and_secret_but_never_emits_values(self):
        for item in (None, "", "garbage", "hostname:\n",
                     "hostname: bergen-ai\nhost name: bad\n",
                     "hostname: bergen-ai\x00\n",
                     "hostname: bergen-ai\n" * 221):
            self.assertIsNone(a.parse_config(item))
        raw = SAMPLE + "foo: password-do-not-display\n"
        with (mock.patch.object(a, "backup_volid", return_value=VOLID),
              mock.patch.object(a, "run", return_value=raw)):
            out = a.report()
        self.assertNotIn("password-do-not-display", str(out))
        self.assertNotIn("192.168.", str(out))

    def test_sanitized_directive_breakdown_catches_deduplicated_keys(self):
        # Prior "3" can represent only two keys because apparmor is in both
        # the explicit high-risk set and the generic LXC catch-all.
        raw = (
            SAMPLE
            + "lxc.apparmor.profile: generated-profile-with-private-value\n"
            + "lxc.cgroup2.devices.allow: c 10:229 rwm\n"
        )
        values = a.parse_config(raw)
        self.assertIsNotNone(values)
        report = a.profile(values)
        self.assertEqual(report["DANGEROUS_CONFIG_DIRECTIVES"], 3)
        self.assertEqual(report["SENSITIVE_UNIQUE_COUNT"], 2)
        self.assertEqual(report["SENSITIVE_DUPLICATE_OVERCOUNT"], 1)
        self.assertEqual(report["SENSITIVE_APPARMOR_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_CGROUP_DEVICE_POLICY_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_HOOK_COUNT"], 0)
        self.assertEqual(report["STATUS"], "REVIEW_REQUIRED")
        self.assertNotIn("generated-profile", str(report))
        self.assertNotIn("10:229", str(report))
        for key in ("SENSITIVE_UNIQUE_COUNT", "SENSITIVE_DUPLICATE_OVERCOUNT",
                    "SENSITIVE_APPARMOR_COUNT", "SENSITIVE_CGROUP_DEVICE_POLICY_COUNT"):
            self.assertIn(key, PLAY.read_text())

    def test_disjoint_sensitive_risk_categories_are_never_restore_clearance(self):
        extra = (
            "hookscript: local:snippets/unsafe.sh\n"
            "lxc.mount.auto: proc:rw\n"
            "lxc.cap.drop: sys_admin\n"
            "lxc.net.0.type: veth\n"
            "lxc.idmap: u 0 100000 65536\n"
            "lxc.seccomp.profile: /private/profile\n"
            "dev0: /dev/sda\n"
        )
        report = a.profile(a.parse_config(SAMPLE + extra))
        self.assertEqual(report["SENSITIVE_HOOK_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_LXC_MOUNT_POLICY_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_CAPABILITY_POLICY_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_LXC_NETWORK_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_ID_MAPPING_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_OTHER_LXC_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_PVE_DEVICE_COUNT"], 1)
        self.assertEqual(report["SENSITIVE_UNIQUE_COUNT"], 7)
        self.assertEqual(report["SENSITIVE_DUPLICATE_OVERCOUNT"], 2)
        self.assertEqual(report["STATUS"], "REVIEW_REQUIRED")
        self.assertNotIn("/dev/sda", str(report))
        self.assertNotIn("unsafe.sh", str(report))
        unknown = a.profile(None)
        self.assertEqual(unknown["SENSITIVE_UNIQUE_COUNT"], "UNVERIFIED")

    def test_script_and_playbook_are_read_only_and_no_log(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        for forbidden in (
            '["pct", "restore"', '["pct", "create"', '["pct", "set"',
            '["pct", "start"', '["pct", "stop"',
            '["pvesm", "free"', '["vzdump"', '["pvesm", "alloc"',
            '["tar", "-x"', "os.unlink", "rm -rf"):
            self.assertNotIn(forbidden, source)
        self.assertIn('"pvesm", "extractconfig", volid', source)
        raw = yaml.safe_load(PLAY.read_text())
        self.assertEqual(
            raw[0]["import_playbook"],
            "audit-bergen-ai-ct110-isolated-restore-feasibility-readonly.yml")
        play = raw[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertFalse(play["gather_facts"])
        cmds = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(cmds), 1)
        self.assertFalse(cmds[0]["changed_when"])
        self.assertTrue(cmds[0]["no_log"])
        self.assertIn("RESTORE_AUTHORIZED=False", PLAY.read_text())
        self.assertIn("ARCHIVE_CONFIG_SANITIZATION=NOT_PROVEN", PLAY.read_text())
