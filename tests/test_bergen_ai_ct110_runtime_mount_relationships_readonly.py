"""No-write CT110 runtime Podman mount source identity checks."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_runtime_mount_relationships_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-runtime-mount-relationships-readonly.yml"
spec = importlib.util.spec_from_file_location("ct110_runtime_mount", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

MERGED = "/var/lib/containers/storage/overlay/" + "a" * 64 + "/merged"
ROOTSRC = "rpool/data/subvol-110-disk-0"


def mount(target, fstype, source, children=None):
    result = dict(target=target, fstype=fstype, source=source)
    if children is not None:
        result["children"] = children
    return result


def sample_tree(bind_source=ROOTSRC + "[/srv/ai/open-webui]", outside=None):
    nested = [
        mount("/proc/cpuinfo", "fuse.lxcfs", "lxcfs[/proc/cpuinfo]"),
        mount("/sys/devices/system/cpu/online", "fuse.lxcfs", "lxcfs[/sys/cpu]"),
        mount(MERGED, "fuse.fuse-overlayfs", "fuse-overlayfs",
              [mount(MERGED + "/app/backend/data", "zfs", bind_source)]),
    ]
    if outside is not None:
        nested.append(outside)
    return [mount("/", "zfs", ROOTSRC, nested)]


class RuntimeMountRelationshipTests(TestCase):
    def test_only_exact_podman_container_bind_merged_root_is_accepted(self):
        good = [{"Mounts": [{
            "Source": "/srv/ai/open-webui",
            "Destination": "/app/backend/data",
            "Type": "bind",
        }], "GraphDriver": {"Data": {"MergedDir": MERGED}}}]
        store = {"store": {"graphRoot": "/var/lib/containers/storage"}}
        self.assertEqual(a.podman_merged(good, store), MERGED)
        self.assertIsNone(a.podman_merged(good, {"store": {"graphRoot": "/elsewhere"}}))
        bad = [{"Mounts": [{"Source": "/host/secret",
                            "Destination": "/app/backend/data", "Type": "bind"}],
                "GraphDriver": {"Data": {"MergedDir": MERGED}}}]
        self.assertIsNone(a.podman_merged(bad, store))
        self.assertIsNone(a.podman_merged([{"Mounts": good[0]["Mounts"],
                                         "GraphDriver": {"Data": {"MergedDir": "/tmp/x"}}}], store))

    def test_mount_tree_exactly_accounts_for_runtime_if_lxcfs_baseline_is_ten(self):
        tree = sample_tree()
        # Two LXCFS samples are not enough; fail-closed to pinned live baseline 10.
        first = a.classify(tree, MERGED, True)
        self.assertEqual(first["LXCFS_SYSTEM_MOUNT_COUNT"], 2)
        self.assertEqual(first["FUSE_OVERLAY_MOUNT_COUNT"], 1)
        self.assertEqual(first["WEBUI_ROOTFS_BIND_MOUNT_COUNT"], 1)
        self.assertEqual(first["UNACCOUNTED_NONPSEUDO_MOUNT_COUNT"], 0)
        self.assertFalse(first["RUNTIME_MOUNTS_MATCH_EXPECTATION"])
        root = tree[0]["children"]
        for i in range(8):
            root.append(mount("/proc/generated" + str(i), "fuse.lxcfs", "lxcfs"))
        verified = a.classify(tree, MERGED, True)
        self.assertTrue(verified["RUNTIME_MOUNTS_MATCH_EXPECTATION"])
        self.assertEqual(verified["LXCFS_SYSTEM_MOUNT_COUNT"], 10)
        self.assertFalse(a.classify(tree, MERGED, False)["RUNTIME_MOUNTS_MATCH_EXPECTATION"])

    def test_other_zfs_bind_is_not_accepted_based_only_on_location(self):
        outsider = mount(MERGED + "/app/backend/extra",
                         "zfs", "nas:/data")
        bad = a.classify(sample_tree(outside=outsider), MERGED, True)
        self.assertEqual(bad["UNACCOUNTED_NONPSEUDO_MOUNT_COUNT"], 1)
        self.assertFalse(bad["RUNTIME_MOUNTS_MATCH_EXPECTATION"])
        wrong = a.classify(sample_tree(bind_source="otherPool/zfs"), MERGED, True)
        self.assertEqual(wrong["WEBUI_ROOTFS_BIND_MOUNT_COUNT"], 0)
        self.assertEqual(wrong["UNACCOUNTED_NONPSEUDO_MOUNT_COUNT"], 1)

    def test_inode_identity_requires_same_device_inode_from_guest(self):
        with mock.patch.object(a, "guest", side_effect=["123:456\n", "123:456\n"]):
            self.assertTrue(a.inode_identity("/srv/ai/open-webui", MERGED + "/app/backend/data"))
        with mock.patch.object(a, "guest", side_effect=["123:456\n", "123:789\n"]):
            self.assertFalse(a.inode_identity("/srv/ai/open-webui", MERGED + "/app/backend/data"))
        with mock.patch.object(a, "guest", return_value=None):
            self.assertFalse(a.inode_identity("/srv/ai/open-webui", MERGED + "/app/backend/data"))

    def test_no_writes_or_hidden_authority_and_valid_ansible(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        self.assertIn('BACKUP_AUTHORIZED=False', source)
        for token in ("vzdump", "pct stop", "pct start", "pct set",
                      "podman run", "podman volume create", "systemctl restart",
                      "os.unlink", "rm -rf", "pvesh set"):
            self.assertNotIn(token, source)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertFalse(play["gather_facts"])
        commands = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        self.assertIn("not ct110_runtime.BACKUP_AUTHORIZED", PLAY.read_text())
