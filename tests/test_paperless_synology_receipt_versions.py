"""Executable identity and replay regression tests for staged NAS v2 journal."""
import hashlib
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "ansible/files/paperless/synology_receipt_versions.py"
spec = importlib.util.spec_from_file_location("synology_receipt_versions", PATH)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

SCOPE = "Familie"
NAME = "Gescanntes Dokument.pdf"
DIGEST = hashlib.sha256(b"%PDF-1.4 example %%EOF").hexdigest()
SIG = [111, 222, 333, 444, 555]


def receipt(sig=SIG, sha=DIGEST, status="SENT"):
    return dict(scope=SCOPE, source=NAME, sha256=sha, signature=list(sig), status=status)


class ReceiptVersionsTests(unittest.TestCase):
    def test_v1_compatibility(self):
        self.assertEqual(v.legacy_id(SCOPE, NAME), hashlib.sha256((SCOPE + "\0" + NAME).encode()).hexdigest())

    def test_replay_same_file_is_stable(self):
        self.assertEqual(v.version_id(SCOPE, NAME, DIGEST, SIG), v.version_id(SCOPE, NAME, DIGEST, list(SIG)))
        self.assertEqual(v.classify_existing([receipt()], SCOPE, NAME, DIGEST, SIG, "v2"), "TRACKED")

    def test_new_file_same_name_and_bytes_has_new_id(self):
        second = [111, 223, 333, 444, 556]
        self.assertNotEqual(v.version_id(SCOPE, NAME, DIGEST, SIG), v.version_id(SCOPE, NAME, DIGEST, second))
        self.assertEqual(v.classify_existing([receipt()], SCOPE, NAME, DIGEST, second, "v2"),
                         "BLOCK_NAME_REUSE_PENDING_ARCHIVE_PROOF")

    def test_new_content_same_name_is_blocked_without_archive_proof(self):
        changed = hashlib.sha256(b"other").hexdigest()
        self.assertNotEqual(v.version_id(SCOPE, NAME, DIGEST, SIG), v.version_id(SCOPE, NAME, changed, SIG))
        self.assertEqual(v.classify_existing([receipt()], SCOPE, NAME, changed, SIG, "v2"),
                         "BLOCK_NAME_REUSE_PENDING_ARCHIVE_PROOF")

    def test_prepared_never_replayed(self):
        self.assertEqual(v.classify_existing([receipt(status="PREPARED")], SCOPE, NAME, DIGEST, SIG, "v2"),
                         "BLOCK_PREPARED")

    def test_older_prepared_blocks_even_with_matching_sent(self):
        old = receipt([1, 2, 3, 4, 5], status="PREPARED")
        self.assertEqual(v.classify_existing([old, receipt()], SCOPE, NAME, DIGEST, SIG, "v2"),
                         "BLOCK_PREVIOUS_PREPARED")

    def test_empty_name_history_is_ready(self):
        self.assertEqual(v.classify_existing([], SCOPE, NAME, DIGEST, SIG, "v2"), "NEW_VERSION_READY")

    def test_identity_is_scope_and_name_specific(self):
        self.assertNotEqual(v.version_id("Familie", NAME, DIGEST, SIG),
                            v.version_id("Eltern", NAME, DIGEST, SIG))
        self.assertNotEqual(v.version_id(SCOPE, NAME, DIGEST, SIG),
                            v.version_id(SCOPE, "Other.pdf", DIGEST, SIG))

    def test_reject_path_traversal_and_invalid_fingerprints(self):
        for name in ("../x.pdf", "x/y.pdf", "x\\y.pdf", "", ".pdf/"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                v.version_id(SCOPE, name, DIGEST, SIG)
        for sig in ([1, 2], [1, 2, 3, 4, -1], [1, 2, 3, 4, True]):
            with self.subTest(sig=sig), self.assertRaises(ValueError):
                v.version_id(SCOPE, NAME, DIGEST, sig)
        with self.assertRaises(ValueError):
            v.version_id(SCOPE, NAME, "not-a-digest", SIG)

    def test_malformed_or_duplicate_receipts_fail_closed(self):
        with self.assertRaises(ValueError):
            v.classify_existing([receipt(), receipt()], SCOPE, NAME, DIGEST, SIG, "v2")
        with self.assertRaises(ValueError):
            v.classify_existing([receipt(status="UNKNOWN")], SCOPE, NAME, DIGEST, SIG, "v2")


if __name__ == "__main__":
    unittest.main()
