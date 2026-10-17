"""Synthetic read-only v1 archive candidate listing; no NAS/Paperless writes."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(CODE))
spec = importlib.util.spec_from_file_location(
    "archive_candidates", CODE / "list_verified_archive_candidates.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SHA = "b" * 64
S = {
    "sender_receipt": "a" * 64 + ".json", "scope": "Familie",
    "source": "Scan.pdf",
    "receiver_source": "Familie/Scan--nas-" + SHA + ".pdf", "sha256": SHA,
}
P = {
    "schema_version": 1, "bridge_receipt": "c" * 24 + ".json",
    "receiver_source": S["receiver_source"], "sha256": SHA,
    "document_id": 12,
}


def jsonl(*records):
    return "\n".join(json.dumps(x, ensure_ascii=True) for x in records)


class ArchiveCandidateListingTests(unittest.TestCase):
    def invoke(self, sender=None, imported=None):
        nas = jsonl(S) if sender is None else sender
        paperless = jsonl(P) if imported is None else imported
        return m.report({"nas": nas, "paperless": paperless})

    def test_verified_candidate_is_listed_without_receipt_identifiers(self):
        lines = self.invoke()
        self.assertEqual(lines[0], "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 1")
        self.assertEqual(lines[1], 'CANDIDATE "Familie/Scan.pdf"')
        self.assertIn("ARCHIVE_NOT_AUTHORIZED", lines)
        self.assertIn("PURGE_NOT_AUTHORIZED", lines)
        self.assertIn("NO_FILES_CHANGED", lines)
        self.assertNotIn(SHA, str(lines))
        self.assertNotIn(P["bridge_receipt"], str(lines))

    def test_no_live_import_is_zero_candidates_not_authorization(self):
        lines = self.invoke(imported="")
        self.assertEqual(lines[0], "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 0")
        self.assertFalse(any(x.startswith("CANDIDATE ") for x in lines))

    def test_no_nas_sources_is_zero_candidates(self):
        self.assertEqual(self.invoke(sender="")[0],
                         "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 0")

    def test_checksum_mismatch_is_not_a_candidate(self):
        bad = dict(P, sha256="d" * 64)
        self.assertEqual(self.invoke(imported=jsonl(bad))[0],
                         "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 0")

    def test_duplicate_nas_source_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_NAS_ARCHIVE_INVENTORY"):
            self.invoke(sender=jsonl(S, S))

    def test_duplicate_live_import_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_LIVE_IMPORT_INVENTORY"):
            self.invoke(imported=jsonl(P, P))

    def test_unsupported_schema_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_LIVE_IMPORT_INVENTORY"):
            self.invoke(imported=jsonl(dict(P, schema_version=2)))

    def test_boolean_paperless_id_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_LIVE_IMPORT_INVENTORY"):
            self.invoke(imported=jsonl(dict(P, document_id=True)))

    def test_traversal_source_blocks(self):
        with self.assertRaises(ValueError):
            self.invoke(sender=jsonl(dict(S, source="../Scan.pdf")))

    def test_second_candidate_is_sorted(self):
        more = {
            "sender_receipt": "e" * 64 + ".json", "scope": "Eltern",
            "source": "Letter.pdf",
            "receiver_source": "Eltern/Letter--nas-" + "f" * 64 + ".pdf",
            "sha256": "f" * 64,
        }
        more_import = {
            "schema_version": 1, "bridge_receipt": "d" * 24 + ".json",
            "receiver_source": more["receiver_source"],
            "sha256": more["sha256"], "document_id": 13,
        }
        lines = self.invoke(sender=jsonl(S, more), imported=jsonl(P, more_import))
        self.assertEqual(lines[0], "V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 2")
        self.assertEqual(lines[1:3], [
            'CANDIDATE "Eltern/Letter.pdf"',
            'CANDIDATE "Familie/Scan.pdf"',
        ])

    def test_missing_bundle_key_blocks(self):
        with self.assertRaisesRegex(ValueError, "INVALID_CANDIDATE_BUNDLE"):
            m.report({"nas": jsonl(S)})

    def test_join_has_no_filesystem_or_remote_calls(self):
        source = (CODE / "list_verified_archive_candidates.py").read_text()
        for forbidden in ("subprocess.run(", "os.rename(", "os.unlink(",
                          "os.replace(", "os.remove(", "archive_one(",
                          "store.publish_event("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
