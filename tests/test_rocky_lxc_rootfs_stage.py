#!/usr/bin/env python3
"""Static security regression tests: no writes without explicit Rocky stage approval."""
from pathlib import Path
import unittest
import yaml

BASE = Path(__file__).resolve().parents[1] / "ansible/playbooks"
PRE = BASE / "audit-rocky-9-8-direct-import-staging-readonly.yml"
STAGE = BASE / "stage-rocky-9-8-lxc-rootfs.yml"


class RockyRootfsStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STAGE.read_text()
        cls.documents = yaml.safe_load(cls.source)
        cls.pre = yaml.safe_load(PRE.read_text())

    def test_readonly_preflight_is_immutable_and_mandatory(self):
        self.assertEqual(len(self.documents), 2)
        self.assertEqual(self.documents[0], {
            "import_playbook": "audit-rocky-9-8-direct-import-staging-readonly.yml",
        })
        self.assertEqual(len(self.pre), 2)
        self.assertIn("rocky_direct_incoming_file", PRE.read_text())
        self.assertIn("rocky_direct_local_config", PRE.read_text())
        self.assertIn("not rocky_direct_incoming_file.stat.exists",
                      PRE.read_text())

    def test_staging_is_file_only_on_exact_pve_host(self):
        play = self.documents[1]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIs(play["become"], True)
        self.assertIs(play["gather_facts"], False)
        self.assertIn("rocky_rootfs_staging_apply", self.source)
        self.assertEqual(
            play["vars"]["rocky_source"],
            "/home/ansible/rocky9-lxc-20261018/rootfs.tar.xz")
        self.assertEqual(
            play["vars"]["rocky_final"],
            "/var/lib/vz/template/cache/rockylinux-9.8-lxc_20261018_amd64.tar.xz")
        self.assertIn("pct_create_authorized: false", self.source)
        self.assertIn("ct701_changed: false", self.source)

    def test_mutations_strictly_gated_and_no_guest_changes(self):
        tasks = self.documents[1]["tasks"]
        copying = [t for t in tasks if "ansible.builtin.copy" in t]
        self.assertEqual(len(copying), 1)
        self.assertEqual(copying[0]["when"], "rocky_apply | bool")
        self.assertIs(copying[0]["ansible.builtin.copy"]["force"], False)
        self.assertIs(copying[0]["ansible.builtin.copy"]["unsafe_writes"], False)
        self.assertEqual(copying[0]["ansible.builtin.copy"]["mode"], "0600")
        self.assertTrue(any("os.link(pending, final" in
                            str(t.get("ansible.builtin.command", {}).get("argv", ""))
                            and t.get("when") == "rocky_apply | bool"
                            for t in tasks))
        for t in tasks:
            self.assertNotIn("ansible.builtin.shell", t)
            self.assertNotIn("ansible.builtin.raw", t)
            self.assertNotIn("ansible.builtin.script", t)
            self.assertNotIn("ansible.builtin.file", t)
            self.assertNotIn("ansible.builtin.template", t)
            if "ansible.builtin.command" in t:
                argv = t["ansible.builtin.command"].get("argv", [])
                self.assertNotIn(argv[:2], [
                    ["pct", "create"], ["pct", "set"], ["pct", "start"],
                    ["pct", "stop"], ["pct", "push"], ["pct", "destroy"],
                ])

    def test_hash_and_atomic_guards(self):
        s = self.source
        for expected in (
            "rocky_direct_source_audit", "rocky_direct_target_file",
            "rocky_direct_incoming_file", "os.O_NOFOLLOW",
            "os.O_CLOEXEC", "os.fsync(fd)", "os.link(pending, final",
            "os.unlink(pending)", "os.fsync(dirfd)",
            "stat.S_ISREG(st.st_mode)", "stat.S_IMODE(st.st_mode) != 0o600",
            "st.st_uid != 0", "st.st_gid != 0",
            "rocky_committed_stat.stat.checksum == rocky_expected_sha256",
            "ROCKY_9_8_ROOTFS_STAGING_READ_ONLY_READY",
            "ROCKY_9_8_ROOTFS_STAGED_SHA256_VERIFIED",
            "not ansible_check_mode",
        ):
            self.assertIn(expected, s)

    def test_default_skip_marker_and_apply_prohibition(self):
        tasks = self.documents[1]["tasks"]
        read_only = [t for t in tasks if "ROCKY_9_8_ROOTFS_STAGING_READ_ONLY_READY"
                     in str(t)]
        self.assertEqual(len(read_only), 1)
        self.assertEqual(read_only[0]["when"], "not rocky_apply | bool")
        for t in tasks:
            if ("ansible.builtin.copy" in t or
                    "os.link(pending, final" in str(t)):
                self.assertEqual(t["when"], "rocky_apply | bool")


if __name__ == "__main__":
    unittest.main()
