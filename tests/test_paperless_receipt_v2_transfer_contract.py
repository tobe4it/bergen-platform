"""Offline v2 sender/receiver identity contract (no live transport)."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/synology_receipt_versions.py"
ACTIVE_SENDER = ROOT / "ansible/files/paperless/synology_scan_sync.py"
spec = importlib.util.spec_from_file_location("v2_staged_contract", SCRIPT)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

SCOPE = "Privat/thomas"
NAME = "Gescanntes Dokument.pdf"
DIGEST = hashlib.sha256(b"%PDF-1.4 example %%EOF").hexdigest()
SIG = [47, 555, 100, 10, 20]
NEXT_SIG = [47, 556, 100, 11, 21]


def legacy(status="SENT", sig=SIG):
    return dict(scope=SCOPE, source=NAME, sha256=DIGEST,
                signature=list(sig), status=status)


class V2TransferContractTests(unittest.TestCase):
    def test_receipt_id_and_receiver_filename_are_bound(self):
        name = v.receiver_filename(SCOPE, NAME, DIGEST, SIG)
        self.assertRegex(name, r"\\Anas-v2-[0-9a-f]{64}\\.pdf\\Z")
        self.assertLess(len(name), 255)
        self.assertEqual(v.receiver_destination(SCOPE, NAME, DIGEST, SIG), SCOPE + "/" + name)
        self.assertEqual(v.receipt_filename(SCOPE, NAME, DIGEST, SIG),
                         v.version_id(SCOPE, NAME, DIGEST, SIG) + ".json")
        self.assertNotIn("Gescanntes", name)

    def test_reused_name_identical_bytes_new_signature_has_separate_dest(self):
        self.assertNotEqual(v.receiver_destination(SCOPE, NAME, DIGEST, SIG),
                            v.receiver_destination(SCOPE, NAME, DIGEST, NEXT_SIG))
        self.assertNotEqual(v.receipt_filename(SCOPE, NAME, DIGEST, SIG),
                            v.receipt_filename(SCOPE, NAME, DIGEST, NEXT_SIG))

    def test_exact_replay_is_stable_but_does_not_authorize_retry(self):
        self.assertEqual(v.receiver_filename(SCOPE, NAME, DIGEST, SIG),
                         v.receiver_filename(SCOPE, NAME, DIGEST, tuple(SIG)))
        self.assertEqual(v.classify_existing([legacy()], SCOPE, NAME, DIGEST, SIG, "v2"),
                         "TRACKED")
        self.assertNotEqual(v.receiver_filename(SCOPE, NAME, DIGEST, SIG),
                            "Gescanntes Dokument--nas-" + DIGEST + ".pdf")

    def test_bind_scope_basename_digest_and_signature(self):
        first = v.receiver_filename(SCOPE, NAME, DIGEST, SIG)
        alternatives = [
            v.receiver_filename("Eltern", NAME, DIGEST, SIG),
            v.receiver_filename(SCOPE, "Andere.pdf", DIGEST, SIG),
            v.receiver_filename(SCOPE, NAME, "0" * 64, SIG),
            v.receiver_filename(SCOPE, NAME, DIGEST, NEXT_SIG),
        ]
        self.assertEqual(len(set([first] + alternatives)), 5)

    def test_reuse_stress_100_file_signatures(self):
        self.assertEqual(len({
            v.receiver_destination(SCOPE, NAME, DIGEST, [47, i, 100, 10 + i, 20 + i])
            for i in range(100)
        }), 100)

    def test_complete_history_is_required_for_preview(self):
        with self.assertRaisesRegex(ValueError, "COMPLETE_LOCKED_HISTORY_REQUIRED"):
            v.preview_transfer(SCOPE, NAME, DIGEST, SIG, [])
        plan = v.preview_transfer(SCOPE, NAME, DIGEST, SIG, [], history_complete=True)
        self.assertEqual(plan["decision"], "NEW_VERSION_READY")
        self.assertTrue(plan["preview_only"])
        self.assertFalse(plan["archive_authorization"])
        self.assertEqual(plan["receiver_path_proof"], "NOT_CHECKED")
        self.assertEqual(plan["sender_receipt"], plan["receipt_id"] + ".json")
        self.assertEqual(json.loads(json.dumps(plan))["signature"], SIG)

    def test_legacy_history_blocks_name_reuse(self):
        self.assertEqual(v.classify_existing([legacy()], SCOPE, NAME, DIGEST, NEXT_SIG, "v2"),
                         "BLOCK_NAME_REUSE_PENDING_ARCHIVE_PROOF")
        self.assertEqual(v.classify_existing(
            [legacy(), legacy(sig=NEXT_SIG)], SCOPE, NAME, DIGEST, SIG, "v2"),
            "BLOCK_NAME_REUSE_PENDING_ARCHIVE_PROOF")

    def test_prepared_ambiguous_and_unknown_states_fail_closed(self):
        self.assertEqual(v.classify_existing([legacy(status="PREPARED")],
                         SCOPE, NAME, DIGEST, SIG, "v2"), "BLOCK_PREPARED")
        self.assertEqual(v.classify_existing(
            [legacy(status="PREPARED"), legacy(sig=NEXT_SIG)],
            SCOPE, NAME, DIGEST, NEXT_SIG, "v2"), "BLOCK_PREVIOUS_PREPARED")
        with self.assertRaisesRegex(ValueError, "UNSAFE_RECEIPT_STATUS"):
            v.classify_existing([legacy(status="ARCHIVED")], SCOPE, NAME, DIGEST, SIG, "v2")
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_RECEIPT_VERSION"):
            v.classify_existing([], SCOPE, NAME, DIGEST, SIG, "v1")
        with self.assertRaisesRegex(ValueError, "DUPLICATE_VERSION_PROOFS"):
            v.classify_existing([legacy(), legacy()], SCOPE, NAME, DIGEST, SIG, "v2")

    def test_forged_or_malformed_v2_receipt_rejected(self):
        correct = dict(legacy(), schema_version=2,
                       receipt_id=v.version_id(SCOPE, NAME, DIGEST, SIG))
        self.assertEqual(v.classify_existing([correct], SCOPE, NAME, DIGEST, SIG, "v2"),
                         "TRACKED")
        with self.assertRaisesRegex(ValueError, "FORGED_V2_RECEIPT_ID"):
            v.classify_existing([dict(correct, receipt_id="v2-" + "f" * 64)],
                                SCOPE, NAME, DIGEST, SIG, "v2")
        with self.assertRaisesRegex(ValueError, "INVALID_V2_RECEIPT"):
            v.classify_existing([dict(correct, schema_version=True)],
                                SCOPE, NAME, DIGEST, SIG, "v2")

    def test_invalid_source_and_path_traversal_rejected(self):
        for scope, name in (("Privat/../Eltern", NAME), ("../Familie", NAME),
                            (SCOPE, "../a.pdf"), (SCOPE, "a/b.pdf"),
                            (SCOPE, "x\\\\y.pdf"), (SCOPE, "a\\x00.pdf")):
            with self.subTest(scope=scope, name=name), self.assertRaises(ValueError):
                v.receiver_filename(scope, name, DIGEST, SIG)

    def test_library_is_pure_and_active_sender_not_switched(self):
        content = SCRIPT.read_text(encoding="utf-8")
        for bad in ("subprocess.", "os.rename(", "os.replace(", "os.unlink(",
                    "open(", ".write_text(", "shutil."):
            self.assertNotIn(bad, content)
        self.assertIn("OFFLINE ONLY", content)
        self.assertNotIn("import synology_receipt_versions",
                         ACTIVE_SENDER.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
