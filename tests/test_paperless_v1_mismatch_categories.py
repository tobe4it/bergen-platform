"""Separate metadata-only drift from actual same-name scan file replacement."""
import importlib.util
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] /
       "ansible/files/paperless/diagnose_synology_v1_receipt_mismatches.py")
spec = importlib.util.spec_from_file_location("mismatch_classifier", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BEFORE = [99, 123, 456, 1000000, 2000000]
SHA = "a" * 64


class MismatchClassifierTests(unittest.TestCase):
    def receipt(self):
        return {"status": "SENT", "signature": list(BEFORE), "sha256": SHA}

    def test_complete_match(self):
        self.assertEqual(mod.classify(self.receipt(), list(BEFORE), SHA), "MATCH")

    def test_ctime_only(self):
        changed = list(BEFORE)
        changed[4] += 999
        self.assertEqual(mod.classify(self.receipt(), changed, SHA),
                         "METADATA_CTIME_ONLY")

    def test_new_inode_even_if_pdf_content_identical(self):
        changed = list(BEFORE)
        changed[1] += 1
        self.assertEqual(mod.classify(self.receipt(), changed, SHA),
                         "FILE_INODE_CHANGED")

    def test_new_content_and_inode(self):
        changed = list(BEFORE)
        changed[1] += 1
        self.assertEqual(mod.classify(self.receipt(), changed, "b"*64),
                         "CONTENT_CHANGED")

    def test_no_receipt_and_uncertain_prepared(self):
        self.assertEqual(mod.classify(None, BEFORE, SHA), "MISSING_RECEIPT")
        self.assertEqual(mod.classify(dict(self.receipt(), status="PREPARED"),
                                      BEFORE, SHA), "PREPARED_RECEIPT")

    def test_same_metadata_different_content(self):
        self.assertEqual(mod.classify(self.receipt(), BEFORE, "f"*64),
                         "CONTENT_CHANGED_SAME_STAT")

    def test_invalid_legacy_receipt_not_repaired(self):
        bad = self.receipt()
        bad["sha256"] = "../bad"
        self.assertEqual(mod.classify(bad, BEFORE, SHA), "INVALID_RECEIPT")

    def test_diagnostics_publish_only_counts_no_original_names(self):
        src = SRC.read_text()
        self.assertIn("SOURCE_CLASS ", src)
        self.assertIn("NAS_SOURCE_AUDIT_READ_ONLY", src)
        self.assertNotIn('print(path', src)
        self.assertNotIn('print(source', src)
        self.assertNotIn('os.replace(', src)
        self.assertNotIn('os.rename(', src)
        self.assertNotIn('unlink(', src)


if __name__ == "__main__":
    unittest.main()
