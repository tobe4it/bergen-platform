"""Synthetic redacted diagnostic tests: no NAS, LXC, subprocess or writes."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
spec = importlib.util.spec_from_file_location(
    "v1_diagnostic", ROOT / "diagnose_v1_import_export_readonly.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SHA = "a" * 64
SOURCE = "Familie/Scan--nas-" + SHA + ".pdf"


class Dir:
    def __init__(self, names=("first.json",)):
        self.names = names

    def glob(self, pattern):
        if pattern != "*.json":
            raise AssertionError("unexpected glob")
        return [Path(name) for name in self.names]


def fake(record=None, *, doc_id=44, fail_read=False, fail_verify=False):
    receipt = record if record is not None else {
        "status": "IMPORTED", "source": SOURCE,
        "sha256": SHA, "document_id": 44,
    }
    def load(_path):
        if fail_read:
            raise ValueError("private receipt name: redacted")
        return receipt, "some-file.pdf", ("admin", "Familie@bergen.intern")
    def verify(*_args):
        if fail_verify:
            raise RuntimeError("confidential raw Paperless traceback")
        return doc_id
    return SimpleNamespace(
        RECEIPTS=Dir(), load_receipt=load, verify=verify)


class DiagnosticTests(unittest.TestCase):
    def test_valid_live_v1_import(self):
        self.assertEqual(m.diagnose(fake()), {
            "bridge_receipts": 1, "imported_receipts": 1,
            "nas_v1_receipts": 1, "verified_v1_imports": 1,
        })

    def test_no_receipts(self):
        mod = fake()
        mod.RECEIPTS = Dir(())
        self.assertEqual(m.diagnose(mod)["verified_v1_imports"], 0)

    def test_not_imported_is_ignored(self):
        r = dict(status="SUBMITTED", source=SOURCE, sha256=SHA, document_id=44)
        self.assertEqual(m.diagnose(fake(record=r))["nas_v1_receipts"], 0)

    def test_non_nas_import_is_ignored(self):
        r = dict(status="IMPORTED", source="Familie/manual.pdf", sha256=SHA, document_id=44)
        self.assertEqual(m.diagnose(fake(record=r))["verified_v1_imports"], 0)

    def test_receipt_exception_is_classified(self):
        with self.assertRaisesRegex(m.DiagnosticFailure, "^BRIDGE_RECEIPT_READ_OR_SCHEMA_FAILED$"):
            m.diagnose(fake(fail_read=True))

    def test_wrong_sha(self):
        with self.assertRaisesRegex(m.DiagnosticFailure, "^IMPORTED_SENDER_DIGEST_MISMATCH$"):
            m.diagnose(fake(record=dict(
                status="IMPORTED", source=SOURCE, sha256="b"*64, document_id=44)))

    def test_invalid_doc_id(self):
        for value in (True, 0, "44", None):
            with self.subTest(value=value), self.assertRaisesRegex(
                    m.DiagnosticFailure, "^IMPORTED_DOCUMENT_ID_INVALID$"):
                m.diagnose(fake(record=dict(
                    status="IMPORTED", source=SOURCE, sha256=SHA, document_id=value)))

    def test_live_verification_exception_redacted(self):
        with self.assertRaisesRegex(m.DiagnosticFailure, "^PAPERLESS_LIVE_VERIFICATION_FAILED$"):
            m.diagnose(fake(fail_verify=True))

    def test_deleted_or_missing_paperless_document_is_distinct(self):
        with self.assertRaisesRegex(m.DiagnosticFailure, "^PAPERLESS_DOCUMENT_NOT_FOUND$"):
            m.diagnose(fake(doc_id=None))

    def test_invalid_live_verifier_result_is_rejected(self):
        for value in (True, 0, "44", -1):
            with self.subTest(value=value), self.assertRaisesRegex(
                    m.DiagnosticFailure, "^PAPERLESS_VERIFIER_INVALID_RESULT$"):
                m.diagnose(fake(doc_id=value))

    def test_live_document_id_mismatch(self):
        with self.assertRaisesRegex(m.DiagnosticFailure, "^PAPERLESS_DOCUMENT_ID_MISMATCH$"):
            m.diagnose(fake(doc_id=45))

    def test_bad_source(self):
        with self.assertRaisesRegex(m.DiagnosticFailure, "^IMPORTED_SOURCE_MALFORMED$"):
            m.diagnose(fake(record=dict(status="IMPORTED", source=None)))

    def test_limit(self):
        mod = fake()
        mod.RECEIPTS = Dir(tuple(f"{x}.json" for x in range(10001)))
        with self.assertRaisesRegex(m.DiagnosticFailure, "^BRIDGE_RECEIPT_LIMIT_EXCEEDED$"):
            m.diagnose(mod)

    def test_source_has_no_mutating_or_external_commands(self):
        source = (ROOT / "diagnose_v1_import_export_readonly.py").read_text()
        for forbidden in ("subprocess.run(", "os.remove(", "os.unlink(",
                          "os.rename(", "os.replace(", "os.mkdir(", "persist(",
                          "store.publish_event(", "print(path", "str(exc)"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
