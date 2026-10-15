"""Offline v2 import reconciliation tests, no Paperless/Django or NAS access."""
import copy
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

CODE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
sys.path.insert(0, str(CODE))
import synology_receipt_v2_store as store
import match_v2_import_proof_offline as matcher

spec = importlib.util.spec_from_file_location(
    "export_imported_scans_v2", CODE / "export_imported_scans_v2.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

SHA = hashlib.sha256(b"%PDF-1.4\nhello\n%%EOF\n").hexdigest()
SIG = [47, 81, 26, 900, 901]


class V2ImportTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.prepared = store.prepared_record(
            "Privat/thomas", "Some scan.pdf", SHA, SIG, "a" * 32)
        self.sent = store.sent_record(self.prepared, {
            "receiver_source": self.prepared["destination"],
            "receiver_sha256": SHA, "new_file_confirmed": True,
        })
        self.imported = {
            "schema_version": 2, "status": "IMPORTED",
            "bridge_receipt": "b" * 24 + ".json",
            "receiver_source": self.prepared["destination"],
            "receipt_id": self.prepared["receipt_id"],
            "sha256": SHA, "document_id": 52,
        }
        self.files = {}
        self.checked = []

    def add(self, name=None, record=None, docname="document.pdf", owner="thomas", group=None):
        name = name or ("b" * 24 + ".json")
        path = self.root / name
        path.write_bytes(b'{"fixture":true}')
        default = {
            "status": "IMPORTED", "source": self.prepared["destination"],
            "sha256": SHA, "document_id": 52,
        }
        self.files[name] = (record if record is not None else default,
                            docname, (owner, group))
        return path

    def fake_reconciler(self, answer=52):
        def load(path):
            return self.files[path.name]
        def verify(name, sha, owner, group):
            self.checked.append((name, sha, owner, group))
            return answer
        return SimpleNamespace(RECEIPTS=self.root, load_receipt=load, verify=verify)

    def test_exporter_requires_live_owner_and_acl_check(self):
        self.add()
        items = export.collect(self.fake_reconciler())
        self.assertEqual(items, [self.imported])
        self.assertEqual(self.checked, [("document.pdf", SHA, "thomas", None)])

    def test_join_matches_exact_nonce_and_blocks_release(self):
        result = matcher.match_offline(self.sent, self.imported)
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["document_id"], 52)
        for key in ("origin_authenticated", "archive_authorized",
                    "fresh_acl_verified_by_this_function", "source_delete_authorized"):
            self.assertIs(result[key], False)

    def test_same_content_different_nonce_does_not_join(self):
        other = store.prepared_record(
            "Privat/thomas", "Some scan.pdf", SHA, SIG, "c" * 32)
        copy_record = copy.deepcopy(self.imported)
        copy_record["receipt_id"] = other["receipt_id"]
        copy_record["receiver_source"] = other["destination"]
        with self.assertRaisesRegex(RuntimeError, "V2_IMPORT_IDENTITY_MISMATCH"):
            matcher.match_offline(self.sent, copy_record)

    def test_same_content_different_scope_does_not_join(self):
        other = store.prepared_record("Familie", "Some scan.pdf", SHA, SIG, "a" * 32)
        incoming = dict(self.imported,
                        receiver_source=other["destination"],
                        receipt_id=other["receipt_id"])
        with self.assertRaisesRegex(RuntimeError, "V2_IMPORT_IDENTITY_MISMATCH"):
            matcher.match_offline(self.sent, incoming)

    def test_import_digest_mismatch_blocks(self):
        incoming = dict(self.imported, sha256="f" * 64)
        with self.assertRaisesRegex(RuntimeError, "V2_IMPORT_IDENTITY_MISMATCH"):
            matcher.match_offline(self.sent, incoming)

    def test_import_document_id_must_be_positive_integer(self):
        for value in (True, 0, -1, "52", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "INVALID_V2_IMPORT_RECORD"):
                    matcher.match_offline(self.sent, dict(self.imported, document_id=value))

    def test_missing_or_forged_bridge_receipt_blocks(self):
        for value in ("random.json", "b" * 24, "../../private.json", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "INVALID_V2_IMPORT_RECORD"):
                    matcher.match_offline(self.sent, dict(self.imported, bridge_receipt=value))

    def test_non_sent_event_blocks_import_join(self):
        with self.assertRaisesRegex(ValueError, "V2_SENT_EVENT_REQUIRED"):
            matcher.match_offline(self.prepared, self.imported)

    def test_import_extra_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_V2_IMPORT_RECORD"):
            matcher.match_offline(self.sent, dict(self.imported, attacker="OK"))

    def test_duplicate_bridge_source_blocks_export(self):
        self.add()
        self.add(name="c" * 24 + ".json")
        with self.assertRaisesRegex(RuntimeError, "INVALID_OR_DUPLICATE_V2_IMPORT_PROOF"):
            export.collect(self.fake_reconciler())

    def test_bridge_with_wrong_live_document_id_fails(self):
        self.add()
        with self.assertRaisesRegex(RuntimeError, "V2_LIVE_IMPORT_ACL_PROOF_FAILED"):
            export.collect(self.fake_reconciler(answer=None))

    def test_v1_or_unrelated_import_ignored(self):
        self.add(record={
            "status": "IMPORTED",
            "source": "Familie/Scan--nas-" + SHA + ".pdf",
            "sha256": SHA, "document_id": 52,
        })
        self.assertEqual(export.collect(self.fake_reconciler()), [])
        self.assertEqual(self.checked, [])

    def test_v2_import_exporter_rejects_forged_bridge_file(self):
        self.add(name="not-a-receipt.json")
        with self.assertRaisesRegex(RuntimeError, "INVALID_BRIDGE_RECEIPT_ID"):
            export.collect(self.fake_reconciler())

    def test_v2_deleted_document_is_never_exported_as_imported(self):
        self.add(record={
            "status": "DELETED_BY_USER", "source": self.prepared["destination"],
            "sha256": SHA, "document_id": 52,
        })
        self.assertEqual(export.collect(self.fake_reconciler()), [])
        self.assertEqual(self.checked, [])

    def test_not_wired_to_original_sender_or_archive(self):
        exporter = (CODE / "export_imported_scans_v2.py").read_text()
        join = (CODE / "match_v2_import_proof_offline.py").read_text()
        for text in (exporter, join):
            for forbidden in ("os.unlink(", "shutil.move(", "os.remove(",
                              "store.publish_event(", "subprocess.run("):
                self.assertNotIn(forbidden, text)
        self.assertIn("ARCHIVE_NOT_AUTHORIZED", exporter)
        self.assertIn("source_delete_authorized", join)
        active = (CODE / "synology_scan_sync.py").read_text()
        self.assertNotIn("export_imported_scans_v2", active)


if __name__ == "__main__":
    unittest.main()
