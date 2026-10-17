"""The one-shot group rollout only composes reviewed one-document playbooks."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ONE_SHOT = ROOT / "ansible/playbooks/commit-paperless-reviewed-groups-v1-once.yml"
SINGLE = ROOT / "ansible/playbooks/commit-paperless-one-group-v1-archive.yml"
AUDIT = ROOT / "ansible/playbooks/list-paperless-v1-archive-candidates.yml"


class ReviewedGroupRolloutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = ONE_SHOT.read_text(encoding="utf-8")
        cls.plays = yaml.safe_load(cls.raw)

    def test_reuses_existing_reviewed_single_file_and_audit(self):
        self.assertTrue(SINGLE.is_file())
        self.assertTrue(AUDIT.is_file())
        self.assertEqual(len(self.plays), 17)
        self.assertEqual(
            self.plays[0]["import_playbook"],
            "list-paperless-v1-archive-candidates.yml")
        for step in self.plays[2:]:
            self.assertEqual(
                step["import_playbook"],
                "commit-paperless-one-group-v1-archive.yml")

    def test_exact_15_reviewed_group_candidates_no_private(self):
        allowed = self.plays[1]["vars"]["approved_group_files"]
        self.assertEqual(len(allowed), 15)
        self.assertEqual(len(set(allowed)), 15)
        self.assertEqual(
            sum(n.startswith("Eltern/") for n in allowed), 7)
        self.assertEqual(
            sum(n.startswith("Familie/") for n in allowed), 8)
        self.assertFalse(any(n.startswith("Privat/") for n in allowed))
        self.assertTrue(all(n.endswith(".pdf") for n in allowed))
        self.assertEqual(
            allowed,
            [step["vars"]["paperless_archive_only"]
             for step in self.plays[2:]])

    def test_single_operation_per_import_and_no_deletion(self):
        for step in self.plays[2:]:
            self.assertEqual(
                set(step),
                {"import_playbook", "vars"})
            self.assertEqual(set(step["vars"]), {"paperless_archive_only"})
        self.assertNotIn("ansible.builtin.shell:", self.raw)
        self.assertNotIn("ansible.builtin.command:", self.raw)
        self.assertNotIn("archive-move.enabled", self.raw)
        self.assertNotIn("os.unlink", self.raw)
        self.assertNotIn("rm -f", self.raw)

    def test_requires_explicit_commit_both_flags(self):
        gate = self.plays[1]["tasks"][0]
        assertions = "\n".join(gate["ansible.builtin.assert"]["that"])
        self.assertIn("paperless_group_batch_commit", assertions)
        self.assertIn("paperless_archive_commit", assertions)
        self.assertIn("is sameas true", assertions)
        self.assertIn("not ansible_check_mode", assertions)

    def test_requires_fresh_full_exact_inventory_and_all_group_names(self):
        first = "\n".join(self.plays[1]["tasks"][0]["ansible.builtin.assert"]["that"])
        self.assertIn("V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 21", first)
        self.assertIn("DELETED_BY_USER_EXCLUDED 2", first)
        self.assertIn("CANDIDATE_AUDIT_COMPLETE", first)
        self.assertIn("(approved_group_files | length) == 15", first)
        second = self.plays[1]["tasks"][1]
        self.assertIn("item | to_json", "\n".join(
            second["ansible.builtin.assert"]["that"]))
        self.assertEqual(second["loop"], "{{ approved_group_files }}")

    def test_original_single_file_preserves_journaling_and_post_audit(self):
        single = SINGLE.read_text(encoding="utf-8")
        self.assertEqual(
            single.count("import_playbook: audit-paperless-import-lifecycle-15-26.yml"),
            2)
        self.assertIn("synology_one_group_archive_release.py", single)
        self.assertIn("ONE_GROUP_PDF_ARCHIVE_COMPLETED", single)
        self.assertIn("POST_MOVE_LIFECYCLE_RECONCILED", single)
        self.assertIn("ALL_RELEASE_GATES_ABSENT", single)
        self.assertIn("ARCHIVE_PURGE_DISABLED", single)


if __name__ == "__main__":
    unittest.main()
