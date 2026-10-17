"""Regression tests for read-only two-sided user-deletion preview."""
import copy
import hashlib
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "ansible/files/paperless"
spec = importlib.util.spec_from_file_location("deleted_by_user", BASE / "preview_deleted_by_user_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

SHA = "a" * 64
DEST = "Privat/thomas/Gebuehren 2--nas-" + SHA + ".pdf"
NAS = {
    "schema_version": 1, "sender_receipt": policy.APPROVED_SENDER,
    "scope": "Privat/thomas", "source": "Gebuehren 2.pdf",
    "receiver_source": DEST, "sha256": SHA,
    "sender_status": "SENT", "nas_original_absent": True,
}
DELETED = {
    "schema_version": 1, "bridge_receipt": policy.APPROVED_BRIDGE,
    "document_id": 26, "receiver_source": DEST, "sha256": SHA,
    "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}


def preview(nas=None, deleted=None, approved_id=26,
            bridge=policy.APPROVED_BRIDGE, sender=policy.APPROVED_SENDER):
    nas = copy.deepcopy(NAS if nas is None else nas)
    deleted = copy.deepcopy(DELETED if deleted is None else deleted)
    out = io.StringIO()
    with redirect_stdout(out):
        policy.preview(json.dumps(nas) + "\nNO_FILES_CHANGED",
                       json.dumps(deleted), approved_id, bridge, sender)
    return out.getvalue().splitlines()


class DeletedByUserTests(unittest.TestCase):
    def test_verified_two_sided_deletion(self):
        lines = preview()
        self.assertTrue(lines[0].startswith("PREVIEW_DELETED_BY_USER 26 "))
        self.assertIn("NAS_ORIGINAL_CONFIRMED_ABSENT", lines)
        self.assertIn("PAPERLESS_DOCUMENT_CONFIRMED_ABSENT", lines)
        self.assertIn("EXCLUDED_FROM_ARCHIVE_MATCH_READY", lines)
        self.assertIn("NO_RECEIPT_STATUS_CHANGED", lines)
        self.assertIn("NO_FILES_CHANGED", lines)
        self.assertNotIn("ARCHIVE_MATCH_READY", lines)

    def test_receipt_key_matches_original_source(self):
        key = hashlib.sha256(b"Privat/thomas\x00Gebuehren 2.pdf").hexdigest() + ".json"
        self.assertEqual(key, policy.APPROVED_SENDER)

    def test_present_nas_source_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ABSENT_NAS_EVIDENCE"):
            preview(nas=dict(NAS, nas_original_absent=False))

    def test_unconfirmed_sender_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ABSENT_NAS_EVIDENCE"):
            preview(nas=dict(NAS, sender_status="PREPARED"))

    def test_wrong_sender_id_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ABSENT_NAS_EVIDENCE"):
            preview(nas=dict(NAS, sender_receipt="b" * 64 + ".json"))

    def test_wrong_scope_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ABSENT_NAS_EVIDENCE"):
            preview(nas=dict(NAS, scope="Familie"))

    def test_wrong_digest_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "PAPERLESS_NAS_PROOF_MISMATCH"):
            preview(deleted=dict(DELETED, sha256="b" * 64))

    def test_wrong_receiver_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_RECEIVER_IDENTITY_MISMATCH"):
            preview(nas=dict(NAS, receiver_source="Privat/thomas/other.pdf"))

    def test_paperless_document_still_exists_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "PAPERLESS_NAS_PROOF_MISMATCH"):
            preview(deleted=dict(DELETED, live_document_absent=False))

    def test_paperless_filename_still_exists_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "PAPERLESS_NAS_PROOF_MISMATCH"):
            preview(deleted=dict(DELETED, original_filename_absent=False))

    def test_wrong_approval_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "EXPLICIT_APPROVAL_MISMATCH"):
            preview(approved_id=27)

    def test_wrong_approval_receipt_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "EXPLICIT_APPROVAL_MISMATCH"):
            preview(sender="c" * 64 + ".json")

    def test_unexpected_nas_field_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_ABSENT_NAS_EVIDENCE"):
            preview(nas=dict(NAS, untrusted=True))

    def test_missing_read_only_marker_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "NAS_READ_ONLY_MARKER_MISSING"):
            policy.preview(json.dumps(NAS), json.dumps(DELETED), 26,
                           policy.APPROVED_BRIDGE, policy.APPROVED_SENDER)

    def test_read_only_code_and_playbook(self):
        for name in ("export_deleted_by_user_nas_evidence.py",
                     "preview_deleted_by_user_policy.py"):
            source = (BASE / name).read_text(encoding="utf-8")
            compile(source, name, "exec")
            for disallowed in ("os.unlink(", "os.remove(", "os.replace(",
                               "shutil.move(", "shutil.copy(", ".write_text("):
                self.assertNotIn(disallowed, source)
        playbook = (ROOT / "ansible/playbooks/preview-paperless-deleted-by-user.yml").read_text()
        self.assertIn("changed_when: false", playbook)
        self.assertNotIn("--commit", playbook)
        self.assertNotIn("state: present", playbook)
        self.assertNotIn("state: absent", playbook)


if __name__ == "__main__":
    unittest.main()
