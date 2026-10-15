"""Pure/offline tests for correlation of staged Paperless v2 proof outputs."""
import copy
import hashlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SRC))
import synology_receipt_v2_store as store
import compare_v2_transfer_evidence_offline as evidence

PDF = b"%PDF-1.4\nnon-sensitive offline fixture\n%%EOF\n"
DIGEST = hashlib.sha256(PDF).hexdigest()
SIG = [47, 456, len(PDF), 800, 900]
SCOPE, BASENAME = "Familie", "Gescanntes Dokument.pdf"
NONCE = "a" * 32


class OfflineTransferEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.prepared = store.prepared_record(SCOPE, BASENAME, DIGEST, SIG, NONCE)
        self.target = self.prepared["destination"].rsplit("/", 1)[1]
        binding = hashlib.sha256(
            (SCOPE + "\0" + self.target + "\0" + DIGEST + "\0" + str(len(PDF)))
            .encode("utf-8")
        ).hexdigest()
        self.stdout = (
            "sending incremental file list\n"
            "<f+++++++++ " + self.target + "\n"
            "\nsent 1,024 bytes  received 35 bytes  2,118.00 bytes/sec\n"
            "total size is 123  speedup is 0.19\n"
        )
        self.receiver = "\n".join([
            "RECEIVER_BINDING " + binding,
            "RECEIVER_SHA256 " + DIGEST,
            "RECEIVER_BYTES " + str(len(PDF)),
            "RECEIVER_POINT_IN_TIME_VERIFIED",
            "NEW_FILE_NOT_ATTESTED",
            "PAPERLESS_IMPORT_NOT_ATTESTED",
            "SENT_NOT_AUTHORIZED",
            "SOURCE_DELETE_NOT_AUTHORIZED",
            "NO_FILES_CHANGED",
        ]) + "\n"

    def compare(self, **changes):
        fields = dict(prepared=self.prepared, rsync_returncode=0,
                      rsync_stdout=self.stdout, rsync_stderr="",
                      receiver_returncode=0, receiver_stdout=self.receiver)
        fields.update(changes)
        return evidence.compare_offline(**fields)

    def test_all_matching_proofs_are_still_not_authorization(self):
        result = self.compare()
        self.assertEqual(result["receipt_id"], self.prepared["receipt_id"])
        self.assertEqual(result["receiver_source"], self.prepared["destination"])
        self.assertEqual(result["receiver_sha256"], DIGEST)
        self.assertEqual(result["receiver_bytes"], len(PDF))
        self.assertTrue(result["rsync_new_file_marker_observed"])
        self.assertTrue(result["receiver_point_in_time_observed"])
        for key in ("origin_authenticated", "durable_prepared_reverified_under_lock",
                    "sent_authorized", "source_delete_authorized"):
            self.assertIs(result[key], False)

    def test_rsync_zero_exit_without_new_file_marker_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "RSYNC_NEW_FILE_MARKER"):
            self.compare(rsync_stdout="sending incremental file list\n\n")

    def test_rsync_wrong_filename_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "RSYNC_NEW_FILE_MARKER"):
            self.compare(rsync_stdout=self.stdout.replace(self.target, "different.pdf"))

    def test_rsync_item_direction_or_file_type_is_blocked(self):
        for mark in (">f+++++++++ ", "<d+++++++++ ", "<f..t...... "):
            with self.subTest(mark=mark):
                with self.assertRaises(ValueError):
                    self.compare(rsync_stdout=self.stdout.replace("<f+++++++++ ", mark))

    def test_duplicate_rsync_marker_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "RSYNC_NEW_FILE_MARKER"):
            self.compare(rsync_stdout=self.stdout.replace(
                "<f+++++++++ " + self.target,
                "<f+++++++++ " + self.target + "\n<f+++++++++ " + self.target))

    def test_extra_rsync_file_event_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "RSYNC_UNEXPECTED_OUTPUT"):
            self.compare(rsync_stdout=self.stdout.replace(
                "<f+++++++++ " + self.target,
                "<f+++++++++ " + self.target + "\n<f+++++++++ another.pdf"))

    def test_rsync_command_failure_or_warning_is_blocked(self):
        for kwargs in (dict(rsync_returncode=23), dict(rsync_returncode=True),
                       dict(rsync_stderr="warning"), dict(rsync_stderr=None)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.compare(**kwargs)

    def test_receiver_command_failure_is_blocked(self):
        for code in (1, True, None):
            with self.subTest(code=code), self.assertRaisesRegex(
                    ValueError, "RECEIVER_PROCESS_UNSUCCESSFUL"):
                self.compare(receiver_returncode=code)

    def test_receiver_swapped_scope_binding_is_blocked(self):
        old_binding = self.receiver.splitlines()[0].split()[1]
        wrong = hashlib.sha256(("Eltern\0" + self.target + "\0" + DIGEST
                                + "\0" + str(len(PDF))).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
            self.compare(receiver_stdout=self.receiver.replace(old_binding, wrong))

    def test_receiver_wrong_nonce_binding_is_blocked(self):
        old_binding = self.receiver.splitlines()[0].split()[1]
        different = self.target.replace(NONCE, "b" * 32)
        wrong = hashlib.sha256((SCOPE + "\0" + different + "\0" + DIGEST
                                + "\0" + str(len(PDF))).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
            self.compare(receiver_stdout=self.receiver.replace(old_binding, wrong))

    def test_receiver_wrong_checksum_and_size_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
            self.compare(receiver_stdout=self.receiver.replace(
                "RECEIVER_SHA256 " + DIGEST, "RECEIVER_SHA256 " + "f" * 64))
        with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
            self.compare(receiver_stdout=self.receiver.replace(
                "RECEIVER_BYTES " + str(len(PDF)),
                "RECEIVER_BYTES " + str(len(PDF) + 1)))

    def test_receiver_missing_negative_authorization_marker_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_REPEATED"):
            self.compare(receiver_stdout=self.receiver.replace(
                "SENT_NOT_AUTHORIZED\n", ""))

    def test_receiver_duplicate_and_unknown_markers_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_REPEATED"):
            self.compare(receiver_stdout=self.receiver + "NO_FILES_CHANGED\n")
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_REPEATED"):
            self.compare(receiver_stdout=self.receiver + "SENT_CONFIRMED\n")

    def test_missing_receiver_binding_is_blocked(self):
        line = self.receiver.splitlines()[0] + "\n"
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_REPEATED"):
            self.compare(receiver_stdout=self.receiver.replace(line, ""))

    def test_fake_prepared_identity_and_nonce_are_blocked(self):
        altered = copy.deepcopy(self.prepared)
        altered["incarnation_nonce"] = "b" * 32
        with self.assertRaisesRegex(ValueError, "INVALID_PREPARED"):
            self.compare(prepared=altered)
        altered = dict(self.prepared, status="SENT")
        with self.assertRaisesRegex(ValueError, "INVALID_PREPARED"):
            self.compare(prepared=altered)

    def test_unicode_and_control_characters_in_outputs_are_blocked(self):
        for altered in (self.stdout + "\0", self.stdout + "\r"):
            with self.assertRaisesRegex(ValueError, "INVALID_RSYNC_OUTPUT"):
                self.compare(rsync_stdout=altered)
        with self.assertRaisesRegex(ValueError, "INVALID_RECEIVER_OUTPUT"):
            self.compare(receiver_stdout=self.receiver + "\0")

    def test_no_live_sender_integration_or_io(self):
        src = (SRC / "compare_v2_transfer_evidence_offline.py").read_text()
        for disallowed in ("subprocess", "rsync(", "os.open(", "os.unlink(",
                           "publish_event(", "sent_record(", "os.replace(",
                           "os.remove(", "urllib", "requests", "delete("):
            self.assertNotIn(disallowed, src)
        self.assertIn("OFFLINE ONLY", src)
        active = (SRC / "synology_scan_sync.py").read_text()
        self.assertNotIn("compare_v2_transfer_evidence_offline", active)

    def test_receiver_binding_producer_and_contract_match(self):
        receiver = (SRC / "verify_receiver_v2_staging.py").read_text()
        self.assertIn('print("RECEIVER_BINDING"', receiver)
        self.assertIn('scope + "\\0" + name + "\\0" + result["receiver_sha256"]', receiver)
        playbook = (ROOT / "ansible/playbooks/audit-paperless-v2-receiver.yml").read_text()
        self.assertIn("RECEIVER_BINDING", playbook)


if __name__ == "__main__":
    unittest.main()
