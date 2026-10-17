"""Offline proof selection tests for a NON-COMMITTING one-file archive preview."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(CODE))

spec = importlib.util.spec_from_file_location(
    "one_v1_preview", CODE / "select_one_verified_lifecycle_archive_preview.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

from test_paperless_list_verified_lifecycle_archive_candidates import (
    bundle as lifecycle_bundle, deletions, S, P, jsonl)


def bundle(only="Familie/Scan.pdf"):
    return dict(lifecycle_bundle(), only=only)


class OneV1ArchivePreviewTests(unittest.TestCase):
    def test_exact_candidate_returns_private_proof_not_filename(self):
        actual = m.select(bundle())
        self.assertEqual(actual, {
            "schema_version": 1,
            "sender_receipt": S["sender_receipt"],
            "bridge_receipt": P["bridge_receipt"],
            "receiver_source": S["receiver_source"],
            "sha256": S["sha256"],
            "document_id": P["document_id"],
        })

    def test_deleted_source_cannot_be_selected(self):
        for name in ["Privat/thomas/Gebuehren.pdf",
                     "Privat/thomas/Gebuehren 2.pdf"]:
            with self.subTest(name=name), self.assertRaisesRegex(
                    RuntimeError, "REQUEST_NOT_A_VERIFIED_LIVE_CANDIDATE"):
                m.select(bundle(name))

    def test_unknown_file_not_a_candidate(self):
        with self.assertRaisesRegex(RuntimeError, "REQUEST_NOT_A_VERIFIED_LIVE_CANDIDATE"):
            m.select(bundle("Familie/unknown.pdf"))

    def test_wrong_scope_not_a_candidate(self):
        with self.assertRaisesRegex(RuntimeError, "REQUEST_NOT_A_VERIFIED_LIVE_CANDIDATE"):
            m.select(bundle("Eltern/Scan.pdf"))

    def test_path_traversal_refused(self):
        with self.assertRaises(RuntimeError):
            m.select(bundle("Familie/../Scan.pdf"))

    def test_tampered_deleted_journal_identity_blocks_selection(self):
        data = bundle()
        changed = deletions()
        changed[0] = dict(changed[0], sha256="e"*64)
        data["paperless_lifecycle"] = jsonl(P, *changed)
        with self.assertRaises(ValueError):
            m.select(data)

    def test_missing_second_journal_blocks_selection(self):
        data = bundle()
        data["paperless_lifecycle"] = jsonl(P, deletions()[0])
        with self.assertRaises(ValueError):
            m.select(data)

    def test_wrong_sender_checksum_blocks_selection(self):
        data = bundle()
        data["nas"] = jsonl(dict(S, sha256="f"*64))
        with self.assertRaises(ValueError):
            m.select(data)

    def test_unverified_import_id_blocks_selection(self):
        data = bundle()
        data["paperless_lifecycle"] = jsonl(dict(P, document_id=False),
                                            *deletions())
        with self.assertRaises(RuntimeError):
            m.select(data)

    def test_missing_complete_audit_marker_blocks_selection(self):
        data = bundle()
        data["lifecycle_report"] = data["lifecycle_report"].replace(
            "IMPORT_LIFECYCLE_RECONCILED", "")
        with self.assertRaises(ValueError):
            m.select(data)

    def test_only_expected_bundle_fields_accepted(self):
        data = bundle()
        data["commit"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_PREVIEW_REQUEST"):
            m.select(data)

    def test_double_count_source_blocks_selection(self):
        data = bundle()
        data["nas"] = jsonl(S, S)
        with self.assertRaises(ValueError):
            m.select(data)

    def test_no_mutating_calls_or_commit_playbook_flags(self):
        source = (CODE / "select_one_verified_lifecycle_archive_preview.py").read_text()
        playbook = (CODE.parent.parent / "playbooks/preview-paperless-one-v1-archive.yml").read_text()
        for snippet in ("subprocess.run(", "os.rename(", "os.unlink(",
                        "os.remove(", "os.replace(", "archive_one(",
                        "os.mkdir(", "os.rmdir("):
            self.assertNotIn(snippet, source)
        self.assertNotIn("{{ '--commit'", playbook)
        self.assertNotIn("argv: [rm,", playbook)
        self.assertIn("ARCHIVE_DRY_RUN_VERIFIED", playbook)
        self.assertIn("no_log: true", playbook)
        self.assertIn("paperless_archive_commit | default(false)", playbook)


if __name__ == "__main__":
    unittest.main()
