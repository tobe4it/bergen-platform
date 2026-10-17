"""Regression: per-PDF group commit must accept future 23+ live imports.

Only inspect the existing reviewed Ansible play; no NAS access and no writes.
The static baseline 22 is the minimum historical import population, not
a fixed upper limit or the expected post-archive original count.
"""
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = (ROOT / "ansible/playbooks"
            / "commit-paperless-one-group-v1-archive.yml")


class DynamicFutureGroupCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))

    def test_pins_exact_live_import_total_from_fresh_full_lifecycle(self):
        self.assertEqual(
            self.plays[0]["import_playbook"],
            "audit-paperless-import-lifecycle-15-26.yml")
        plays = [p for p in self.plays if isinstance(p, dict)
                 and p.get("hosts") == "venombox"]
        self.assertEqual(len(plays), 2)
        before = plays[0]["tasks"]
        matching = [task for task in before
                    if "group_before_import_count" in task.get(
                        "ansible.builtin.set_fact", {})]
        self.assertEqual(len(matching), 1)
        formula = matching[0]["ansible.builtin.set_fact"]["group_before_import_count"]
        self.assertIn("PAPERLESS_LIVE_IMPORTED [0-9]+", formula)
        self.assertIn("lifecycle_report.stdout_lines", formula)

    def test_before_uses_dynamic_counts_and_keeps_fixed_deletion_journals(self):
        p = next(p for p in self.plays if p.get("hosts") == "venombox")
        a = next(t for t in p["tasks"] if
                 t.get("name", "").startswith("Require some remaining"))
        rules = "\n".join(a["ansible.builtin.assert"]["that"])
        self.assertIn("group_before_import_count | int >= 22", rules)
        self.assertIn(
            "group_before_source_count | int + group_before_archive_count | int == group_before_import_count | int",
            rules)
        self.assertIn("NAS_CURRENT_ORIGINALS_VERIFIED", rules)
        self.assertIn("group_before_import_count | string", rules)
        self.assertIn("DELETED_BY_USER 2", rules)
        self.assertNotIn("PAPERLESS_LIVE_IMPORTED 22", rules)

    def test_after_requires_exact_single_source_to_archive_delta(self):
        p = [p for p in self.plays if p.get("hosts") == "venombox"][-1]
        a = next(t for t in p["tasks"]
                 if "exact one-move delta" in t.get("name", ""))
        rules = "\n".join(a["ansible.builtin.assert"]["that"])
        for text in (
            "group_before_import_count | string",
            "group_before_source_count | int - 1",
            "group_before_archive_count | int + 1",
            "NAS_CURRENT_ORIGINALS_VERIFIED",
            "DELETED_BY_USER 2",
            "IMPORT_LIFECYCLE_RECONCILED",
            "NO_FILES_CHANGED",
        ):
            with self.subTest(text=text):
                self.assertIn(text, rules)
        self.assertNotIn("PAPERLESS_LIVE_IMPORTED 22", rules)
        self.assertNotIn("NAS_CURRENT_ORIGINALS_VERIFIED 22", rules)

    def test_never_authorizes_purge_or_private_scopes(self):
        text = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("^(Familie|Eltern)/", text)
        self.assertIn("EXACT_RELEASE_GATE_REVOKED", text)
        self.assertIn("ARCHIVE_PURGE_DISABLED", text)
        self.assertIn("ALL_RELEASE_GATES_ABSENT", text)
        self.assertNotIn("archive-move.enabled: true", text)
        self.assertNotIn("Privat/thomas)/", text)


if __name__ == "__main__":
    unittest.main()
