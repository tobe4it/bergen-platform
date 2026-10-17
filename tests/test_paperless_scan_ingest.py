"""Offline test contracts for staged Paperless scan ingestion."""
import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/scripts/paperless_scan_map_preflight.py"
EXAMPLE = ROOT / "docs/examples/paperless.scan-ingest.example.yml"
GITIGNORE = ROOT / ".gitignore"

spec = importlib.util.spec_from_file_location("scan_preflight", SCRIPT)
scan_preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_preflight)


class PaperlessScanIngestTests(unittest.TestCase):
    def setUp(self):
        self.mapping = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_complete_explicit_example(self):
        self.assertEqual(scan_preflight.validate(self.mapping),
                         {"private": 1, "group": 2})

    def test_personal_scope_cannot_reassign_owner(self):
        self.mapping["sources"][0]["principal"] = "andereperson"
        with self.assertRaisesRegex(ValueError, "private target"):
            scan_preflight.validate(self.mapping)

    def test_admin_and_anonymous_are_not_document_principals(self):
        for name in ("admin", "AnonymousUser"):
            with self.subTest(name=name):
                self.mapping["sources"][0]["principal"] = name
                self.mapping["sources"][0]["consume_subdir"] = f"Privat/{name}"
                with self.assertRaisesRegex(ValueError, "invalid private principal"):
                    scan_preflight.validate(self.mapping)

    def test_shared_groups_must_both_be_present(self):
        self.mapping["sources"].pop()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            scan_preflight.validate(self.mapping)

    def test_unknown_shared_group_is_rejected(self):
        self.mapping["sources"][1]["principal"] = "Alle"
        self.mapping["sources"][1]["consume_subdir"] = "Alle"
        with self.assertRaisesRegex(ValueError, "invalid group route"):
            scan_preflight.validate(self.mapping)

    def test_duplicate_destination_is_rejected(self):
        duplicate = dict(self.mapping["sources"][0])
        duplicate["id"] = "another"
        duplicate["source_path"] = "/mnt/sds/elsewhere"
        self.mapping["sources"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate consume_subdir"):
            scan_preflight.validate(self.mapping)

    def test_overlapping_nas_sources_are_rejected(self):
        self.mapping["sources"][1]["source_path"] = (
            self.mapping["sources"][0]["source_path"] + "/children"
        )
        with self.assertRaisesRegex(ValueError, "overlaps"):
            scan_preflight.validate(self.mapping)

    def test_relative_or_traversing_nas_source_is_rejected(self):
        for candidate in ("relative", "/mnt/sds/../private", "/mnt//sds"):
            with self.subTest(candidate=candidate):
                self.mapping["sources"][0]["source_path"] = candidate
                with self.assertRaises(ValueError):
                    scan_preflight.validate(self.mapping)

    def test_application_storage_cannot_be_a_nas_source(self):
        self.mapping["sources"][0]["source_path"] = "/srv/bergen-paperless/media"
        with self.assertRaisesRegex(ValueError, "not Paperless storage"):
            scan_preflight.validate(self.mapping)

    def test_same_source_differing_only_by_case_denied(self):
        self.mapping["sources"][1]["source_path"] = self.mapping["sources"][0]["source_path"].upper()
        with self.assertRaisesRegex(ValueError, "duplicate source_path"):
            scan_preflight.validate(self.mapping)

    def test_wrong_private_destination_denied(self):
        self.mapping["sources"][0]["consume_subdir"] = "Privat/unrelated"
        with self.assertRaisesRegex(ValueError, "private target"):
            scan_preflight.validate(self.mapping)

    def test_schema_incomplete_or_extraneous_denied(self):
        for invalid in ({}, [], {"sources": []}, {"sources": [], "extra": True}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                scan_preflight.validate(invalid)

    def test_real_nas_paths_ignored_by_git(self):
        self.assertIn("ansible/vars/paperless*.local.yml",
                      GITIGNORE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
