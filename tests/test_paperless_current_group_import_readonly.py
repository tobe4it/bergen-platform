"""Privacy-safe exact group NAS SENT -> live Paperless join, including mtime drift."""
import ast
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "ansible/files/paperless"
NAS = CODE / "export_current_group_source_evidence_readonly.py"
PAPERLESS = CODE / "export_live_group_imports_readonly.py"
JOIN = CODE / "join_current_group_import_evidence_readonly.py"
PLAY = ROOT / "ansible/playbooks/diagnose-paperless-current-group-imports-readonly.yml"

spec = importlib.util.spec_from_file_location("group_live_join_readonly", JOIN)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def nas_stream(rows):
    return "\n".join(
        [json.dumps(r) for r in rows] +
        ["NAS_CURRENT_GROUP_EVIDENCE_COMPLETE", "NO_FILES_CHANGED",
         "ARCHIVE_NOT_AUTHORIZED"])


def live_stream(rows):
    return "\n".join(
        [json.dumps(r) for r in rows] +
        ["LIVE_GROUP_IMPORT_EVIDENCE_COMPLETE", "NO_FILES_CHANGED",
         "ARCHIVE_NOT_AUTHORIZED"])


def current(name, kind="MATCH", sha="a"*64):
    return {"receiver_source": "Familie/" + name + "--nas-" + sha + ".pdf",
            "sha256": sha, "classification": kind}


def imported(item, i):
    return {"receiver_source": item["receiver_source"],
            "sha256": item["sha256"], "document_id": i,
            "bridge_receipt": f"{i:024x}.json"}


class CurrentGroupImportReadOnlyTests(unittest.TestCase):
    def test_four_group_current_two_live_one_drift_waiting(self):
        rows = [current("a"), current("b"), current("c"),
                current("d", "SAME_INODE_METADATA_DRIFT")]
        proof = [imported(rows[0], 101), imported(rows[1], 102)]
        answer = mod.join({"nas": nas_stream(rows), "paperless": live_stream(proof)})
        self.assertEqual(answer, {"total": 4, "live": 2, "waiting": 2,
                                  "metadata_drift": 1, "metadata_drift_live": 0})

    def test_drift_same_bytes_can_be_imported_without_archive_release(self):
        row = current("scan", "SAME_INODE_METADATA_DRIFT")
        answer = mod.join({"nas": nas_stream([row]),
                           "paperless": live_stream([imported(row, 5)])})
        self.assertEqual(answer["metadata_drift_live"], 1)
        self.assertEqual(answer["live"], 1)
        self.assertEqual(answer["metadata_drift"], 1)

    def test_existing_historically_archived_import_may_be_extra(self):
        row = current("current")
        extra = current("archived")
        answer = mod.join({"nas": nas_stream([row]),
                           "paperless": live_stream([imported(row, 101),
                                                       imported(extra, 102)])})
        self.assertEqual(answer["live"], 1)
        self.assertEqual(answer["total"], 1)

    def test_sha_mismatch_rejected_not_counted(self):
        row = current("scan")
        wrong = imported(row, 1)
        wrong["sha256"] = "b" * 64
        with self.assertRaisesRegex(RuntimeError, "INVALID_RECEIVER_IDENTITY"):
            mod.join({"nas": nas_stream([row]), "paperless": live_stream([wrong])})

    def test_duplicate_identity_and_unexpected_status_rejected(self):
        row = current("scan")
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_OR_UNCLASSIFIED"):
            mod.join({"nas": nas_stream([row, row]),
                      "paperless": live_stream([])})
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_PAPERLESS"):
            proof = imported(row, 1)
            mod.join({"nas": nas_stream([row]),
                      "paperless": live_stream([proof, proof])})
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_OR_UNCLASSIFIED"):
            bad = dict(row, classification="NEW_INODE_UNARCHIVED")
            mod.join({"nas": nas_stream([bad]),
                      "paperless": live_stream([])})

    def test_no_missing_terminals_allowed(self):
        row = current("scan")
        with self.assertRaisesRegex(RuntimeError, "MISSING_VERIFIED_PROOF_TERMINAL"):
            mod.join({"nas": json.dumps(row),
                      "paperless": live_stream([])})

    def test_nas_drift_requires_same_inode_size_and_sha(self):
        nas_spec = importlib.util.spec_from_file_location("group_nas_readonly", NAS)
        nas = importlib.util.module_from_spec(nas_spec)
        nas_spec.loader.exec_module(nas)
        original = [42, 10, 900, 100, 200]
        now = [42, 10, 900, 300, 400]
        self.assertEqual(nas.classify(now, original, "a"*64, "a"*64),
                         "SAME_INODE_METADATA_DRIFT")
        self.assertEqual(nas.classify(original, original, "a"*64, "a"*64),
                         "MATCH")
        with self.assertRaisesRegex(RuntimeError, "UNVERIFIED_SOURCE_RECEIPT"):
            nas.classify(now, original, "b"*64, "a"*64)
        with self.assertRaises(RuntimeError):
            nas.classify([42, 11, 900, 300, 400], original, "a"*64, "a"*64)

    def test_playbook_never_logs_raw_identity_and_never_changes_documents(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        raw_tasks = [task for task in play["tasks"] if task.get("register") in {
            "group_nas_source_evidence", "group_paperless_live_evidence",
            "group_current_import_summary"}]
        self.assertEqual(len(raw_tasks), 3)
        for task in raw_tasks:
            self.assertIs(task["no_log"], True)
            self.assertIs(task["changed_when"], False)
        source = PLAY.read_text()
        self.assertIn("export_current_group_source_evidence_readonly.py", source)
        self.assertIn("export_live_group_imports_readonly.py", source)
        self.assertIn("join_current_group_import_evidence_readonly.py", source)
        self.assertNotIn("sender_once_result", source)
        self.assertNotIn("archive-move.enabled: true", source)
        self.assertNotIn("source_delete_commit", source)
        for code in (NAS, PAPERLESS, JOIN):
            script = code.read_text()
            ast.parse(script)
            self.assertNotIn("os.rename(", script)
            self.assertNotIn("os.unlink(", script)
            self.assertNotIn("os.replace(", script)
            self.assertNotIn("write_receipt(", script)
            self.assertNotIn("archive_one(", script)


if __name__ == "__main__":
    unittest.main()
