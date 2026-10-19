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

    def test_diagnostics_distinguish_inaccessible_host_bind_and_container_namespace(self):
        tree = sample_tree()
        inspected = [{"State": {"Running": True, "Pid": 4123}}]
        source = "13:42"
        other = "13:43"
        with mock.patch.object(a, "checked_inode", side_effect=[source, None, source]):
            details = a.identity_details(inspected, tree, MERGED)
        self.assertEqual(details["SOURCE_INODE_READ"], "AVAILABLE")
        self.assertEqual(details["MERGED_INODE_READ"], "UNAVAILABLE")
        self.assertEqual(details["PROCESS_ROOT_INODE_READ"], "AVAILABLE")
        self.assertEqual(details["MERGED_INODE_RELATION"], "UNVERIFIED")
        self.assertEqual(details["PROCESS_ROOT_INODE_RELATION"], "IDENTICAL")
        self.assertEqual(details["BIND_TARGET"], "EXACT_MERGED_DATA_TARGET")
        self.assertEqual(details["BIND_FSTYPE_RELATION"], "MATCHES_ROOT")
        self.assertEqual(details["BIND_SOURCE_RELATION"], "MATCHES_ROOT_SOURCE")
        with mock.patch.object(a, "checked_inode", side_effect=[source, other, other]):
            details = a.identity_details(inspected, tree, MERGED)
        self.assertEqual(details["MERGED_INODE_RELATION"], "DIFFERENT")
        self.assertEqual(details["PROCESS_ROOT_INODE_RELATION"], "DIFFERENT")

    def test_broken_or_spoofed_bind_cannot_be_accepted_by_diagnostic(self):
        tree = sample_tree(bind_source="nas:/outside")
        with mock.patch.object(a, "checked_inode", return_value=None):
            details = a.identity_details([{"State": {"Running": True, "Pid": 4123}}], tree, MERGED)
        self.assertEqual(details["BIND_SOURCE_RELATION"], "DIFFERS_FROM_ROOT_SOURCE")
        self.assertEqual(details["MERGED_INODE_RELATION"], "UNVERIFIED")
        self.assertEqual(details["PROCESS_ROOT_INODE_RELATION"], "UNVERIFIED")
        tree = sample_tree()
        tree[0]["children"] = [item for item in tree[0]["children"]
                               if item["target"] != MERGED]
        details = a.mounted_bind_characteristics(tree, MERGED)
        self.assertEqual(details["BIND_TARGET"], "NOT_UNIQUE_OR_MISSING")
        self.assertIsNone(a.running_podman_pid([{"State": {"Running": True, "Pid": -1}}]))
        self.assertIsNone(a.running_podman_pid([{"State": {"Running": False, "Pid": 4123}}]))
        self.assertIsNone(a.running_podman_pid([{"State": {"Running": True, "Pid": True}}]))

    def test_inode_queries_return_only_fixed_status_no_raw_inode_or_pid(self):
        with mock.patch.object(a, "guest", side_effect=["123:456\\n", "invalid"]):
            self.assertEqual(a.checked_inode(a.SOURCE), "123:456")
            self.assertIsNone(a.checked_inode(MERGED + a.DST))
        self.assertEqual(a.comparison("5:6", "5:6"), "IDENTICAL")
        self.assertEqual(a.comparison("5:6", "5:7"), "DIFFERENT")
        self.assertEqual(a.comparison(None, "5:7"), "UNVERIFIED")

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
