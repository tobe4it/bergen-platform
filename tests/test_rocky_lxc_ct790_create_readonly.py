#!/usr/bin/env python3
"""Static, synthetic safety tests for isolated CT790 creation-readiness gate."""
import importlib.util
from collections import Counter
from pathlib import Path
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "ansible/playbooks/audit-rocky-9-8-ct790-create-readonly.yml"
SRC = ROOT / "ansible/files/nextcloud"
sys.path.insert(0, str(SRC))
spec = importlib.util.spec_from_file_location(
    "rocky_idmap_audit", SRC / "audit_rocky_lxc_idmap_metadata.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class Ct790CreateReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = P.read_text()
        cls.plays = yaml.safe_load(cls.source)

    def test_imported_pve_staged_template_verification_is_mandatory(self):
        self.assertEqual(len(self.plays), 3)
        self.assertEqual(self.plays[0], {
            "import_playbook": "audit-rocky-9-8-staged-template-readonly.yml"
        })
        self.assertEqual(self.plays[1]["hosts"], "bp-controller")
        self.assertEqual(self.plays[1]["connection"], "local")
        self.assertIs(self.plays[1]["become"], False)
        self.assertEqual(self.plays[2]["hosts"], "venombox")
        self.assertIs(self.plays[2]["become"], True)

    def test_only_readonly_commands_on_both_hosts(self):
        allowed = {"ansible.builtin.command", "ansible.builtin.assert",
                   "ansible.builtin.debug"}
        for play in self.plays[1:]:
            self.assertIs(play["gather_facts"], False)
            self.assertIs(play["any_errors_fatal"], True)
            for task in play["tasks"]:
                modules = {key for key in task if key.startswith("ansible.builtin.")}
                self.assertTrue(modules <= allowed, task["name"])
                if "ansible.builtin.command" in task:
                    self.assertIs(task["changed_when"], False)
                    argv = task["ansible.builtin.command"]["argv"]
                    self.assertNotIn(argv[:2], [
                        ["pct", "create"], ["pct", "start"], ["pct", "set"],
                        ["pct", "clone"], ["pct", "template"],
                        ["pvesm", "alloc"], ["pveam", "download"],
                    ])
        self.assertIn("[pct, help, create]", self.source)
        self.assertIn("[pvesh, get, /storage, --output-format, json]", self.source)
        self.assertNotIn("rocky_rootfs_staging_apply", self.source)

    def test_source_identity_mapping_thresholds(self):
        self.assertEqual(audit.MAX_CONTAINER_ID, 65535)
        self.assertEqual(audit.classify_owner(0, 0), (False, False))
        self.assertEqual(audit.classify_owner(65535, 65535), (False, False))
        self.assertEqual(audit.classify_owner(65536, 0), (True, False))
        self.assertEqual(audit.classify_owner(0, 65536), (False, True))
        with self.assertRaisesRegex(
                audit.rootfs.AuditBlocked, "INVALID_UID_GID"):
            audit.classify_owner(-1, 1)
        with self.assertRaisesRegex(
                audit.rootfs.AuditBlocked, "INVALID_UID_GID"):
            audit.classify_owner(1, -1)

    def test_pax_metadata_counts_keys_not_string_values(self):
        # Real POSIX PAX metadata is a mapping of string names to string
        # values. Treating this as a Counter mapping fails with TypeError
        # for repeated keys and invalid values at sum().
        headers = [
            {"mtime": "1789484591.916", "SCHILY.xattr.security.capability": "AQID"},
            {"mtime": "1789484592.222", "GNU.sparse.name": "file"},
            {"LIBARCHIVE.xattr.user.comment": "encoded"},
        ]
        counts = Counter()
        for member_headers in headers:
            audit.count_pax_header_keys(counts, member_headers)
        self.assertEqual(counts["mtime"], 2)
        self.assertEqual(counts["SCHILY.xattr.security.capability"], 1)
        self.assertEqual(counts["GNU.sparse.name"], 1)
        self.assertEqual(counts["LIBARCHIVE.xattr.user.comment"], 1)
        self.assertEqual(sum(counts.values()), 5)
        self.assertTrue(all(isinstance(v, int) for v in counts.values()))
        with self.assertRaisesRegex(
                audit.rootfs.AuditBlocked, "INVALID_PAX_HEADERS"):
            audit.count_pax_header_keys(counts, ["mtime"])
        with self.assertRaisesRegex(
                audit.rootfs.AuditBlocked, "INVALID_PAX_HEADER_KEY"):
            audit.count_pax_header_keys(counts, {42: "mtime"})

    def test_never_update_counter_with_pax_value_mapping(self):
        source = (SRC / "audit_rocky_lxc_idmap_metadata.py").read_text()
        self.assertIn("counter.update(headers.keys())", source)
        self.assertIn("count_pax_header_keys(pax_keys, member.pax_headers)",
                      source)
        self.assertNotIn("pax_keys.update(member.pax_headers)", source)
        self.assertIn('reason = "AUDITOR_INTERNAL_ERROR"', source)

    def test_rootfs_and_subid_checks_are_strict(self):
        for key in (
            "rootfs.inspect_archive(",
            "sha.hexdigest() == rootfs.SHA256",
            "default_idmap_compatibility",
            "archive_extracted",
            "ct701_changed",
        ):
            self.assertIn(key, (SRC / "audit_rocky_lxc_idmap_metadata.py").read_text())
        for key in (
            "hostvars['bp-controller'].rocky_ct790_ownership is defined",
            "not (rocky_ct790_ownership.stdout | from_json).pct_create_authorized",
            "os.O_NOFOLLOW", "os.O_CLOEXEC",
            "check('/etc/subuid')", "check('/etc/subgid')",
            "'rootdir' in rocky_zfs_storage.content.split(',')",
            "not (rocky_zfs_storage.disable | default(false) | bool)",
            "container_network_interfaces_planned: 0",
            "container_start_planned: false",
            "pct_create_authorized: false",
            "new_guest_created: false",
            "ct701_changed: false",
        ):
            self.assertIn(key, self.source)


if __name__ == "__main__":
    unittest.main()
