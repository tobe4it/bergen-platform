"""Offline tests for sanitized mount directive diagnosis of CT110."""
import ast
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_mount_directives_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-mount-directives-readonly.yml"
spec = importlib.util.spec_from_file_location("bergen_ai_mount_diag", SCRIPT)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
BASE = ("hostname: bergen-ai\n"
        "unprivileged: 1\n"
        "rootfs: local-zfs:subvol-110-disk-0,size=40G\n"
        "net0: name=eth0,bridge=vmbr1\n")


class CT110MountDiagnosisTest(TestCase):
    def test_normal_auto_system_mounts_are_not_persistent_mountpoints(self):
        report = diag.classify_config(
            BASE + "lxc.mount.auto: proc:rw sys:rw cgroup:rw\n")
        self.assertEqual(report["LXC_MOUNT_AUTO"],
                         "STANDARD_PSEUDO_DIRECTIVES_PRESENT")
        self.assertEqual(report["PVE_MP_DIRECTIVES"], "NONE")
        self.assertEqual(report["LXC_MOUNT_ENTRY"], "ABSENT")

    def test_nonstandard_auto_or_custom_bind_never_assumed_safe(self):
        report = diag.classify_config(
            BASE + "lxc.mount.auto: proc:rw unknown:data\n"
            + "lxc.mount.entry: /mnt/data srv/data none bind,create=dir 0 0\n")
        self.assertEqual(report["LXC_MOUNT_AUTO"], "NONSTANDARD_OR_UNKNOWN")
        self.assertEqual(report["LXC_MOUNT_ENTRY"],
                         "OTHER_OR_PERSISTENT_TARGETS_PRESENT")
        self.assertEqual(report["LXC_MOUNT_ENTRY_COUNT"], 1)
        self.assertEqual(diag.classify_entry([
            "/dev/fuse dev/fuse none bind,create=file 0 0"]),
            "DEVICE_OR_PSEUDO_TARGETS_PRESENT")

    def test_pve_mp_and_hook_appear_only_as_categories(self):
        report = diag.classify_config(BASE +
            "mp0: /private/customer-folder,mp=/data,backup=0\n"
            "lxc.hook.pre-start: /private/secret\n")
        self.assertEqual(report["PVE_MP_DIRECTIVES"], "PRESENT")
        self.assertEqual(report["PVE_MP_COUNT"], 1)
        self.assertEqual(report["OTHER_MOUNT_OR_EXCLUDE_DIRECTIVES"], "PRESENT")
        self.assertNotIn("/private/customer-folder", json.dumps(report))
        self.assertNotIn("/private/secret", json.dumps(report))

    def test_guest_identity_and_bad_directives_fail_closed(self):
        self.assertIsNone(diag.classify_config(BASE.replace("bergen-ai", "wrong")))
        self.assertIsNone(diag.classify_config(BASE.replace("unprivileged: 1", "")))
        self.assertEqual(diag.classify_entry(["bad"]), "UNVERIFIED")
        self.assertEqual(diag.classify_auto(["proc:rw 0bad/evil"]), "NONSTANDARD_OR_UNKNOWN")

    def test_guest_data_location_classifies_without_printing_path(self):
        def safe(argv, limit=100000):
            return "" if "test" in argv else "/"
        with mock.patch.object(diag, "command", side_effect=safe):
            self.assertEqual(diag.dir_and_mount("/srv/ai/open-webui"), "GUEST_ROOTFS")
        with mock.patch.object(diag, "command", return_value=None):
            self.assertEqual(diag.dir_and_mount("/srv/ai/open-webui"), "UNVERIFIED")

    def test_playbook_and_script_are_strictly_nonmutating(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        for banned in ("vzdump", "pct set", "pct start", "pct stop", "pct reboot",
                       "systemctl restart", "ifreload -a", "pvesh set", "os.unlink"):
            self.assertNotIn(banned, source)
        self.assertIn("BACKUP_AUTHORIZED=False", source)
        with redirect_stdout(io.StringIO()) as sink:
            diag.emit(CT110_CONFIG_IDENTITY="UNVERIFIED")
        output = sink.getvalue()
        self.assertNotIn("/srv/ai/open-webui", output)
        self.assertIn('"BACKUP_AUTHORIZED": false', output)
        self.assertIn('"BACKUP_EXECUTED": false', output)

        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        commands = [x for x in play["tasks"] if "ansible.builtin.command" in x]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        self.assertIn("not mount_diag.BACKUP_AUTHORIZED", PLAY.read_text())
