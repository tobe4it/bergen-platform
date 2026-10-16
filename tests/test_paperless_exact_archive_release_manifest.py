"""Synthetic preparation-only manifest tests; no NAS, gates or file writes."""
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(CODE))
import build_one_archive_release_manifest as b

SOURCE = "Familie/Scan.pdf"
SHA = "a"*64
NAME_HASH = hashlib.sha256(b"Familie\0Scan.pdf").hexdigest() + ".json"
PROOF = {
    "schema_version": 1, "sender_receipt": NAME_HASH,
    "bridge_receipt": "b"*24 + ".json",
    "receiver_source": "Familie/Scan--nas-" + SHA + ".pdf",
    "sha256": SHA, "document_id": 123,
}


class ManifestBuilderTests(unittest.TestCase):
    def test_exact_single_file_and_10_minute_expiry(self):
        result = b.build_manifest(SOURCE, PROOF, 1700000000)
        self.assertEqual(result["site"], "paperless-scan")
        self.assertEqual(result["scope"], "Familie")
        self.assertEqual(result["source"], "Scan.pdf")
        self.assertEqual(result["document_id"], 123)
        self.assertEqual(result["expires_at"] - result["issued_at"], 600)
        self.assertEqual(
            json.loads(b.canonical_bytes(result)), result)
        self.assertTrue(b.canonical_bytes(result).endswith(b"\n"))

    def test_other_site_is_not_authorized(self):
        with self.assertRaises(ValueError):
            b.build_manifest("Privat/thomas/Scan.pdf", PROOF, 1700000000)

    def test_path_traversal_and_hidden_files_denied(self):
        for value in ("Familie/../Scan.pdf", "Familie/.hidden.pdf",
                      "Familie/sub/Scan.pdf", "Familie/a.txt",
                      "Other/Scan.pdf", "Scan.pdf", "Familie/../../Scan.pdf",
                      "Familie/x\\y.pdf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                b.build_manifest(value, PROOF, 1700000000)

    def test_false_claimed_sender_is_denied(self):
        with self.assertRaises(ValueError):
            b.build_manifest(SOURCE, dict(PROOF, sender_receipt="c"*64+".json"),
                             1700000000)

    def test_source_digest_and_receiver_identity_are_bound(self):
        for field, value in (
                ("sha256", "d"*64),
                ("receiver_source", "Eltern/Scan--nas-"+SHA+".pdf"),
                ("bridge_receipt", "../a.json"),
                ("document_id", True),
                ("document_id", -3),
                ("schema_version", 2)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                b.build_manifest(SOURCE, dict(PROOF, **{field: value}),
                                 1700000000)

    def test_unsupported_fields_denied(self):
        with self.assertRaises(ValueError):
            b.build_manifest(SOURCE, dict(PROOF, wildcard=True), 1700000000)

    def test_bad_expiry_epoch_is_denied(self):
        for stamp in (None, True, "1700000000", -1):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                b.build_manifest(SOURCE, PROOF, stamp)

    def test_only_pure_builder_no_gate_creation(self):
        body = (CODE / "build_one_archive_release_manifest.py").read_text()
        for forbidden in ("open(", "os.open(", "subprocess", "write_text(",
                          "write_bytes(", "ssh", "ansible", "touch(",
                          "rename(", "unlink("):
            self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main()
