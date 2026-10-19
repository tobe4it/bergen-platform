"""Offline security regression for CT110 guest mount blocker diagnostics."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_guest_mount_blockers_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-guest-mount-blockers-readonly.yml"
spec = importlib.util.spec_from_file_location("mount_diag", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def mount(target, fstype, source, children=None):
    result = {"target": target, "fstype": fstype, "source": source}
    if children is not None:
        result["children"] = children
    return result


class CT110GuestMountBlockersTest(TestCase):
    def test_lxcfs_and_guest_etc_are_classified_not_approved(self):
        tree = [mount("/", "zfs", "rpool/subvol-110", [
            mount("/proc/cpuinfo", "fuse.lxcfs", "lxcfs"),
            mount("/etc/hosts", "ext4", "/dev/hostdisk"),
            mount("/dev/shm", "tmpfs", "tmpfs"),
        ])]
        result = a.diagnose(tree)
        self.assertEqual(result["PREVIOUS_PREFLIGHT_BLOCKER_COUNT"], 2)
        self.assertEqual(result["LXCFS_SYSTEM_COUNT"], 1)
        self.assertEqual(result["ETC_IDENTITY_COUNT"], 1)
        self.assertEqual(result["OTHER_NONPSEUDO_COUNT"], 0)
        self.assertEqual(result["BLOCKER_CLASSES"], ["ETC_IDENTITY_TARGET", "LXCFS_SYSTEM_TARGET"])

    def test_nfs_or_data_mount_is_not_mistaken_for_system(self):
        tree = [mount("/", "zfs", "rpool/subvol-110", [
            mount("/srv/ai/extra", "nfs4", "nas:/private"),
            mount("/mnt/outside", "ext4", "/dev/sdc"),
            mount("/home/userdata", "ext4", "/dev/x"),
            mount("/proc/cpuinfo", "nfs4", "nas:/spoof"),
        ])]
        result = a.diagnose(tree)
        self.assertEqual(result["PREVIOUS_PREFLIGHT_BLOCKER_COUNT"], 4)
        self.assertEqual(result["OTHER_NONPSEUDO_COUNT"], 4)
        self.assertEqual(result["LXCFS_SYSTEM_COUNT"], 0)
        self.assertEqual(result["BLOCKER_CLASSES"], [
            "OTHER_AI_DATA", "OTHER_CONTAINER_STORAGE",
            "OTHER_MOUNTED_STORAGE", "OTHER_PROC_OR_SYS"
        ])

    def test_profiles_break_down_all_four_unknown_mounts_without_raw_paths(self):
        tree = [mount("/", "zfs", "rpool/secret", [
            mount("/proc/cpuinfo", "fuse.lxcfs", "lxcfs"),
            mount("/proc/other", "fuse.lxcfs", "lxcfs"),
            mount("/proc/newmount", "nfs4", "nas:/secret"),
            mount("/var/lib/containers/storage/overlay/x/merged",
                  "fuse.fuse-overlayfs", "fuse-overlayfs"),
            mount("/home/private/hidden", "ext4", "/dev/secret"),
            mount("/dev/shm", "tmpfs", "tmpfs"),
        ])]
        output = a.diagnose(tree)
        self.assertEqual(output["OTHER_NONPSEUDO_COUNT"], 4)
        self.assertEqual(output["OVERLAY_MOUNT_COUNT"], 1)
        self.assertEqual(output["UNRESOLVED_PROFILES"], [
            "HOME_TREE:BLOCK_OR_COW_FS:DEVICE_SOURCE:1",
            "PODMAN_GRAPH_TREE:FUSE_OVERLAYFS:OVERLAY_SOURCE:1",
            "PROC_TREE:FUSE_LXCFS:LXCFS_SOURCE:1",
            "PROC_TREE:NETWORK_FS:NETWORK_SOURCE:1",
        ])
        self.assertNotIn("/secret", str(output))
        self.assertNotIn("/home/private", str(output))
        self.assertNotIn("/var/lib/containers/storage", str(output))

    def test_overlay_in_podman_graph_not_automatically_backup_safe(self):
        tree = [mount("/", "zfs", "rpool", [
            mount("/var/lib/containers/storage/overlay/x/merged",
                  "overlay", "overlay"),
            mount("/var/lib/containers/storage/volumes/external",
                  "nfs4", "nas:/private"),
        ])]
        result = a.diagnose(tree)
        self.assertEqual(result["OVERLAY_MOUNT_COUNT"], 1)
        self.assertEqual(result["PREVIOUS_PREFLIGHT_BLOCKER_COUNT"], 1)
        self.assertEqual(result["OTHER_NONPSEUDO_COUNT"], 1)
        self.assertEqual(result["UNRESOLVED_PROFILES"], [
            "PODMAN_GRAPH_TREE:NETWORK_FS:NETWORK_SOURCE:1"])

    def test_any_ambiguous_or_missing_source_fails_closed(self):
        self.assertRaises(ValueError, a.diagnose, [])
        self.assertRaises(ValueError, a.diagnose,
                          [mount("/proc/cpuinfo", "fuse.lxcfs", "lxcfs")])
        self.assertRaises(ValueError, a.diagnose,
                          [mount("/", "zfs", None)])
        self.assertRaises(ValueError, a.diagnose,
                          [mount("/", "zfs", "rpool"), mount("/", "zfs", "rpool")])
        self.assertRaises(ValueError, a.diagnose,
                          [mount("/", "zfs", "rpool", ["invalid node"])])

    def test_script_and_playbook_cannot_write_or_authorize_backup(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        for forbidden in ("vzdump", "pct stop", "pct start", "pct set",
                          "systemctl restart", "pvesh set", "rm -rf",
                          "os.remove", "os.unlink"):
            self.assertNotIn(forbidden, source)
        self.assertIn("BACKUP_AUTHORIZED=False", source)
        self.assertIn("UNRESOLVED_PROFILES", source)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertFalse(play["gather_facts"])
        commands = [task for task in play["tasks"] if "ansible.builtin.command" in task]
        self.assertEqual(len(commands), 1)
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        self.assertTrue(commands[0]["no_log"])
        self.assertIn("not guest_mount_audit.BACKUP_AUTHORIZED", PLAY.read_text())
