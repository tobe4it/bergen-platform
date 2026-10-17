"""The automatic v1 group entrypoint only reuses the accepted one-PDF runner."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / "ansible/playbooks/archive-next-verified-paperless-group-v1.yml"
SINGLE = ROOT / "ansible/playbooks/commit-paperless-one-group-v1-archive.yml"


class AutoGroupPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = AUTO.read_text(encoding="utf-8")
        cls.plays = yaml.safe_load(cls.raw)

    def test_one_fresh_audit_and_one_reviewed_one_file_import(self):
        self.assertEqual(len(self.plays), 3)
        self.assertEqual(
            self.plays[0]["import_playbook"],
            "list-paperless-v1-archive-candidates.yml")
        self.assertEqual(
            self.plays[2]["import_playbook"],
            "commit-paperless-one-group-v1-archive.yml")
        self.assertTrue(SINGLE.is_file())
        self.assertEqual(len([p for p in self.plays
                              if p.get("import_playbook") ==
                              "commit-paperless-one-group-v1-archive.yml"]), 1)

    def test_opt_in_both_flags_and_no_unconditional_commit(self):
        tasks = self.plays[1]["tasks"]
        expr = "\n".join(tasks[0]["ansible.builtin.assert"]["that"])
        self.assertIn("paperless_group_auto_archive", expr)
        self.assertIn("paperless_archive_commit", expr)
        self.assertIn("is sameas true", expr)
        self.assertIn("not ansible_check_mode", expr)
        self.assertIn("paperless_group_auto_selected_only",
                      self.plays[2]["vars"]["paperless_archive_only"])
        self.assertIn("when", self.plays[2])
        self.assertIn("length", "\n".join(self.plays[2]["when"]))

    def test_selector_is_read_only_and_no_private_pdfs_allowed(self):
        tasks = self.plays[1]["tasks"]
        selection = next(t for t in tasks if t.get("register") == "group_archive_auto_selection")
        self.assertEqual(selection["changed_when"], False)
        self.assertIs(selection["no_log"], True)
        self.assertIn("select_next_verified_group_archive.py",
                      " ".join(selection["ansible.builtin.command"]["argv"]))
        self.assertIn("^(Familie|Eltern)/", self.raw)
        self.assertNotIn("Privat/thomas/", self.raw)
        self.assertNotIn("archive-move.enabled: true", self.raw)
        self.assertNotIn("shell:", self.raw)
        self.assertNotIn("rm -f", self.raw)

    def test_existing_reviewed_runner_has_pre_post_lifecycle_and_purge_off(self):
        source = SINGLE.read_text(encoding="utf-8")
        self.assertEqual(
            source.count("import_playbook: audit-paperless-import-lifecycle-15-26.yml"), 2)
        self.assertIn("ONE_GROUP_PDF_ARCHIVE_COMPLETED", source)
        self.assertIn("ARCHIVE_PURGE_DISABLED", source)
        self.assertIn("ALL_RELEASE_GATES_ABSENT", source)


if __name__ == "__main__":
    unittest.main()
