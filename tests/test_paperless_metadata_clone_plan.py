"""Pure offline unit tests for zero-write VMID/capacity clone plan.

No Proxmox access, no container creation, no restore, no network changes.
"""
import ast
import json
import math
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/audit_isolated_metadata_clone_plan.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-metadata-clone-plan.yml"
CONFIG = (
    "hostname: bergen-paperless\n"
    "unprivileged: 1\n"
    "features: nesting=1,keyctl=1\n"
    "rootfs: local-zfs:subvol-126-disk-0,size=10G\n"
    "mp0: local-zfs:subvol-126-disk-1,mp=/srv/bergen-paperless,"
    "backup=1,size=8G\n"
    "net0: name=eth0,bridge=vmbr0,ip=dhcp\n"
)
STORAGE = "Name Type Status Total Used Available %\n" + (
    "local-zfs zfspool active 100000000 20000000 80000000 20.0%\n")
VMIDS = json.dumps([
    {"vmid": 126, "type": "lxc"},
    {"vmid": 816, "type": "lxc"},
    {"vmid": 825, "type": "lxc"},
])


class MetadataOfflineClonePlanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code = SCRIPT.read_text()
        cls.tree = ast.parse(code)
        needed = {"SOURCE", "STORAGE", "PREFERRED_ID", "ALTERNATE_IDS",
                  "MIN_FREE_GIB", "MAX_SOURCE_GIB"}
        methods = {"require", "volume_size_gib", "source_volumes",
                   "storage_available_kib", "allocated_vmids", "plan"}
        nodes = []
        for node in cls.tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in needed for t in node.targets
            ):
                nodes.append(node)
            if isinstance(node, ast.ClassDef) and node.name == "Blocked":
                nodes.append(node)
            if isinstance(node, ast.FunctionDef) and node.name in methods:
                nodes.append(node)
        cls.context = {"json": json, "math": math, "re": re}
        exec(compile(ast.Module(body=nodes, type_ignores=[]),
                     "<offline-clone-planning>", "exec"), cls.context)

    def test_expected_offline_candidate_and_configured_capacity(self):
        out = self.context["plan"](CONFIG, STORAGE, VMIDS)
        self.assertEqual(out["CANDIDATE_VMID"], 826)
        self.assertEqual(out["SOURCE_ROOTFS_CONFIGURED_GIB"], 10)
        self.assertEqual(out["SOURCE_DATA_MOUNT_CONFIGURED_GIB"], 8)
        self.assertEqual(out["PLANNING_MINIMUM_FREE_GIB"], 27)
        self.assertEqual(out["TEST_NET_INTERFACES"], "NONE_PROPOSED")
        self.assertEqual(out["NETWORK_ISOLATION_PROVEN"], "NO")
        self.assertEqual(out["VMID_STATE"], "FREE_AT_AUDIT_NOT_RESERVED")

    def test_occupied_preferred_vmid_uses_other_free_pool_member(self):
        ids = json.loads(VMIDS) + [{"vmid": 826, "type": "qemu"}]
        out = self.context["plan"](CONFIG, STORAGE, json.dumps(ids))
        self.assertEqual(out["CANDIDATE_VMID"], 820)

    def test_no_cluster_free_vmid_refuses_to_plan(self):
        ids = json.loads(VMIDS) + [
            {"vmid": i, "type": "lxc"} for i in range(820, 830)
            if i != 825
        ]
        with self.assertRaises(self.context["Blocked"]):
            self.context["plan"](CONFIG, STORAGE, json.dumps(ids))

    def test_unreviewed_additional_mount_refuses_planning(self):
        with self.assertRaises(self.context["Blocked"]):
            self.context["source_volumes"](CONFIG + "mp1: /mnt/paperless,mp=/data\n")

    def test_storage_too_small_refuses(self):
        small = STORAGE.replace("80000000", "1000000")
        with self.assertRaises(self.context["Blocked"]):
            self.context["plan"](CONFIG, small, VMIDS)

    def test_source_must_be_unprivileged_and_existing_data_mount_backed_up(self):
        fn = self.context["source_volumes"]
        with self.assertRaises(self.context["Blocked"]):
            fn(CONFIG.replace("unprivileged: 1", "unprivileged: 0"))
        with self.assertRaises(self.context["Blocked"]):
            fn(CONFIG.replace("backup=1", "backup=0"))

    def test_no_restore_start_or_guest_network_mutation_in_script(self):
        source = SCRIPT.read_text()
        for forbidden in (
            '"pct", "restore"', '"pct", "start"', "pvesm alloc",
            "zfs create", "qm create", "pct create", "write_text(",
            "systemctl start", "subprocess.Popen", "shell=True",
        ):
            self.assertNotIn(forbidden, source)

    def test_ansible_preserves_read_only_refusal_and_host(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["hosts"], "venombox")
        self.assertIn("PAPERLESS_CLONE_PLAN_READ_ONLY_ONLY",
                      PLAY.read_text())
        for task in plays[0]["tasks"]:
            for forbidden in (
                "ansible.builtin.copy", "ansible.builtin.file",
                "ansible.builtin.systemd_service",
                "ansible.builtin.template",
                "community.general.proxmox",
            ):
                self.assertNotIn(forbidden, task)


if __name__ == "__main__":
    unittest.main()
