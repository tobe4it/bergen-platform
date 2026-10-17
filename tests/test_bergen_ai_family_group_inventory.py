"""Synthetic safety and privacy tests for stable Open WebUI family groups."""
from pathlib import Path
import importlib.util
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "ansible/filter_plugins/bergen_ai_family_group_inventory.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-static-family-groups.yml"
spec = importlib.util.spec_from_file_location("family_audit", PLUGIN)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

EXPECT = {"family": "Synthetic Commons", "adults": "Synthetic Adults", "children": "Synthetic Children"}


def groups(version="0.12.3"):
    items = []
    for index, role in enumerate(("family", "adults", "children"), 1):
        group = {"id": "synthetic-group-" + str(index), "name": EXPECT[role],
                 "member_count": index, "permissions": {"private": "NEVER_DISCLOSE"}}
        if version == "0.12.3":
            group["parent_group_id"] = None
        items.append(group)
    return items


class FamilyInventory(unittest.TestCase):
    def check(self, gs=None, expected=None, version="0.12.3"):
        return module.family_group_inventory(
            groups(version) if gs is None else gs,
            EXPECT if expected is None else expected, version)

    def test_valid_flat_groups_and_legacy_version(self):
        for version, label in (("0.12.3", "PRESENT_ROOT"), ("v0.10.2", "PRESENT_LEGACY_FLAT")):
            result = self.check(version=version)
            for role in ("FAMILY_GROUP", "ADULTS_GROUP", "CHILDREN_GROUP"):
                self.assertEqual(result[role], label)
            self.assertEqual(result["STATUS"], "INVENTORY_PRESENT_ONLY")
            self.assertEqual(result["MEMBERSHIP_SEPARATION_PROVEN"], "NO")
            self.assertEqual(result["RESOURCE_ACL_SEPARATION_PROVEN"], "NO")
            self.assertEqual(result["EXISTING_SESSIONS_REVOKED"], "NO")
            self.assertEqual(result["GROUPS_OR_PERMISSIONS_CHANGED"], "NO")

    def test_missing_duplicate_nested_and_unverified_hierarchy(self):
        gs = groups()
        self.assertEqual(self.check(gs[:-1])["CHILDREN_GROUP"], "MISSING")
        self.assertEqual(self.check(gs + [{**gs[0], "id": "new-id"}])["FAMILY_GROUP"], "DUPLICATE")
        gs[2]["parent_group_id"] = gs[1]["id"]
        self.assertEqual(self.check(gs)["CHILDREN_GROUP"], "NESTED_REVIEW_REQUIRED")
        gs[2].pop("parent_group_id")
        self.assertEqual(self.check(gs)["CHILDREN_GROUP"], "HIERARCHY_UNVERIFIED")

    def test_fail_closed_for_unreviewed_version_and_bad_expected(self):
        for version in ("0.10.3", "0.12.4", "v0.12.99", "", None):
            with self.subTest(version=version), self.assertRaises(module.AnsibleFilterError):
                self.check(version=version)
        for mapping in ({}, {"family": "A", "adults": "B"},
                        {"family": "A", "adults": "A", "children": "C"},
                        {"family": "A", "adults": "B", "children": " C "},
                        {"family": "A", "adults": "B", "children": ""}):
            with self.subTest(mapping=mapping), self.assertRaises(module.AnsibleFilterError):
                self.check(expected=mapping)

    def test_malformed_group_responses(self):
        for gs in ({}, ["broken"], [dict(id="", name="x")],
                   [{**groups()[0]}, {**groups()[0]}], [{}], [{}] * 1001):
            with self.subTest(gs=type(gs).__name__), self.assertRaises(module.AnsibleFilterError):
                self.check(gs=gs)

    def test_summary_contains_no_user_group_or_permissions_data(self):
        gs = groups()
        gs[0]["user_id"] = "SYNTHETIC_PERSON_SECRET"
        result = self.check(gs)
        as_string = str(result)
        for secret in ("SYNTHETIC_PERSON_SECRET", "NEVER_DISCLOSE", "synthetic-group",
                       *EXPECT.values()):
            self.assertNotIn(secret, as_string)

    def test_playbook_is_read_only_and_bound_to_one_approved_target(self):
        data = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(data), 1)
        p = data[0]
        self.assertFalse(p["gather_facts"])
        self.assertEqual(p["serial"], 1)
        self.assertIn("__no_approved_family_host__", p["hosts"])
        tasks = p["tasks"]
        assert_flags = tasks[0]["ansible.builtin.assert"]["that"]
        for flag in ("ansible_play_hosts_all | length == 1",
                     "bergen_ai_family_audit_approved | default(false) | bool",
                     "vault_open_webui_admin_token is defined"):
            self.assertIn(flag, assert_flags)
        permitted = {"ansible.builtin.assert", "ansible.builtin.uri",
                     "ansible.builtin.set_fact", "ansible.builtin.debug"}
        for task in tasks:
            actions = [x for x in task if x.startswith("ansible.builtin.")]
            self.assertEqual(len(actions), 1)
            self.assertIn(actions[0], permitted)
        gets = [t for t in tasks if "ansible.builtin.uri" in t]
        self.assertEqual(len(gets), 2)
        for t in gets:
            uri = t["ansible.builtin.uri"]
            self.assertEqual(uri["method"], "GET")
            self.assertTrue(uri["url"].startswith("http://127.0.0.1:3000/"))
            self.assertFalse(uri["use_proxy"])
            self.assertTrue(t["no_log"])
            self.assertFalse(t["changed_when"])
        self.assertEqual(
            {t["ansible.builtin.uri"]["url"] for t in gets},
            {"http://127.0.0.1:3000/api/version",
             "http://127.0.0.1:3000/api/v1/groups/"}
        )
        source = PLAY.read_text()
        self.assertNotIn("ansible.builtin.copy", source)
        self.assertNotIn("ansible.builtin.command", source)
        self.assertNotIn("ansible.builtin.systemd_service", source)
        self.assertNotIn("192.168.", source)
        self.assertNotIn("thebergens.net", source)
        self.assertNotIn("GROUPS_OR_PERMISSIONS_CHANGED=YES", source)


if __name__ == "__main__":
    unittest.main()
