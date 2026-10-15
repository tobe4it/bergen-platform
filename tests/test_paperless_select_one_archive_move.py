"""Offline controller-side matching tests for exactly one v1 archive candidate."""
import importlib.util
import json
import unittest
from pathlib import Path

MODULE = (Path(__file__).resolve().parents[1] /
          "ansible/files/paperless/select_one_verified_archive_move.py")
spec = importlib.util.spec_from_file_location("archive_select_one", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

S = {
    "sender_receipt": "a" * 64 + ".json",
    "scope": "Familie",
    "source": "Scan.pdf",
    "receiver_source": "Familie/Scan--nas-" + "b" * 64 + ".pdf",
    "sha256": "b" * 64,
}
P = {
    "schema_version": 1,
    "bridge_receipt": "c" * 24 + ".json",
    "receiver_source": S["receiver_source"],
    "sha256": S["sha256"],
    "document_id": 12,
}
ONLY = "Familie/Scan.pdf"


def jsonl(*items):
    return "\n".join(json.dumps(i) for i in items)


class ControllerSelectorTests(unittest.TestCase):
    def select(self, nas=None, paperless=None, only=ONLY):
        return m.select_one(
            jsonl(S) if nas is None else nas,
            jsonl(P) if paperless is None else paperless,
            only)

    def test_selects_unique_join(self):
        result = self.select()
        self.assertEqual(result, {
            "schema_version": 1,
            "sender_receipt": S["sender_receipt"],
            "bridge_receipt": P["bridge_receipt"],
            "receiver_source": S["receiver_source"],
            "sha256": S["sha256"],
            "document_id": P["document_id"],
        })

    def test_missing_paperless_document_denied(self):
        with self.assertRaisesRegex(RuntimeError, "LIVE_IMPORT_NOT_MATCHED"):
            self.select(paperless="")

    def test_missing_nas_sender_denied(self):
        with self.assertRaisesRegex(RuntimeError, "EXACT_SENDER_RECEIPT_NOT_FOUND"):
            self.select(nas="")

    def test_wrong_checksum_denied(self):
        with self.assertRaisesRegex(RuntimeError, "LIVE_IMPORT_NOT_MATCHED"):
            self.select(paperless=jsonl(dict(P, sha256="d" * 64)))

    def test_wrong_document_id_denied(self):
        for docid in (None, True, 0, -3, "12"):
            with self.subTest(docid=docid), self.assertRaisesRegex(
                    RuntimeError, "INVALID_LIVE_IMPORT_INVENTORY"):
                self.select(paperless=jsonl(dict(P, document_id=docid)))

    def test_duplicate_sender_denied(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_NAS_ARCHIVE_INVENTORY"):
            self.select(nas=jsonl(S, S))

    def test_duplicate_paperless_denied(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_LIVE_IMPORT_INVENTORY"):
            self.select(paperless=jsonl(P, P))

    def test_wrong_scope_and_traversal_denied(self):
        for value in ("Familie/../Scan.pdf", "Privat/unknown/Scan.pdf",
                      "Familie/../../x.pdf", "Eltern/no.txt", "Familie/sub/Scan.pdf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.select(only=value)

    def test_unrelated_document_not_mistaken_for_selected(self):
        extra = dict(P, bridge_receipt="d" * 24 + ".json",
                     receiver_source="Eltern/else.pdf")
        proof = self.select(paperless=jsonl(P, extra))
        self.assertEqual(proof["document_id"], 12)

    def test_duplicate_json_keys_fail_closed(self):
        with self.assertRaises(ValueError):
            self.select(nas='{"scope":"Familie","scope":"Eltern"}')

    def test_import_record_unknown_schema_denied(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_LIVE_IMPORT_INVENTORY"):
            self.select(paperless=jsonl(dict(P, schema_version=2)))

    def test_no_archive_commands_in_selection_code(self):
        source = MODULE.read_text()
        for forbidden in ("os.rename(", "os.unlink(", "subprocess.run(",
                          "archive_one(", "os.remove(", "os.replace("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
