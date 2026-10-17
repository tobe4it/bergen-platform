"""Pure tests for next eligible imported group PDF, never a direct archive grant."""
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] /
          "ansible/files/paperless/select_next_verified_group_archive.py")
spec = importlib.util.spec_from_file_location("group_auto_selector", SOURCE)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def report(names):
    return "\n".join(
        ["V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES " + str(len(names)),
         "DELETED_BY_USER_EXCLUDED 2"]
        + ["CANDIDATE " + json.dumps(n, ensure_ascii=True) for n in names]
        + ["CANDIDATE_AUDIT_COMPLETE", "NO_FILES_CHANGED",
           "ARCHIVE_NOT_AUTHORIZED", "PURGE_NOT_AUTHORIZED"])


class AutomaticGroupCandidateTests(unittest.TestCase):
    def test_idle_after_all_groups_archived(self):
        result = selector.choose(report(
            ["Privat/thomas/one.pdf", "Privat/thomas/another.pdf"]))
        self.assertEqual(result["status"], "IDLE")
        self.assertIsNone(result["only"])
        self.assertEqual(result["private_untouched"], 2)

    def test_new_imported_group_is_selected_without_touching_private(self):
        result = selector.choose(report(
            ["Privat/thomas/private.pdf", "Eltern/new-scan.pdf",
             "Familie/new-scan.pdf"]))
        self.assertEqual(result["only"], "Eltern/new-scan.pdf")
        self.assertEqual(result["groups_ready"], 2)
        self.assertEqual(result["private_untouched"], 1)

    def test_repeated_run_idle_after_archive_with_private_sources_only(self):
        initial = selector.choose(report(
            ["Familie/first.pdf", "Privat/thomas/private.pdf"]))
        self.assertEqual(initial["status"], "READY")
        after = selector.choose(report(["Privat/thomas/private.pdf"]))
        self.assertEqual(after["status"], "IDLE")
        self.assertIsNone(after["only"])

    def test_unicode_escaped_source(self):
        name = "Familie/Büro – neuer Scan.pdf"
        self.assertEqual(selector.choose(report([name]))["only"], name)

    def test_rejects_duplicate_candidates(self):
        with self.assertRaises(ValueError):
            selector.choose(report(["Familie/a.pdf", "Familie/a.pdf"]))

    def test_rejects_incomplete_or_forged_audit(self):
        full = report(["Familie/a.pdf"])
        for sample in (full.replace("CANDIDATE_AUDIT_COMPLETE", ""),
                       full.replace("NO_FILES_CHANGED", "FILES_CHANGED"),
                       full.replace("DELETED_BY_USER_EXCLUDED 2",
                                    "DELETED_BY_USER_EXCLUDED 1"),
                       full.replace("CANDIDATES 1", "CANDIDATES 2"),
                       full.replace("PURGE_NOT_AUTHORIZED",
                                    "PURGE_AUTHORIZED"),
                       full + "\nextra"):
            with self.subTest(sample=sample[-55:]):
                with self.assertRaises(ValueError):
                    selector.choose(sample)

    def test_rejects_unsafe_names_and_extra_fields(self):
        for name in ("Privat/thomas/subdir/x.pdf", "Familie/../x.pdf",
                     "Familie/.hidden.pdf", "Other/x.pdf",
                     "Familie/x.txt", "Familie/x\\evil.pdf"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    selector.choose(report([name]))

    def test_empty_verified_inventory_is_idle(self):
        self.assertEqual(selector.choose(report([]))["status"], "IDLE")


if __name__ == "__main__":
    unittest.main()
