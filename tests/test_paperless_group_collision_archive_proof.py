"""Offline safety requirements for read-only archived-name reuse preflight."""
import ast
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "ansible/files/paperless/diagnose_synology_group_collision_archive_proof.py"
AUDITOR = ROOT / "ansible/files/paperless/audit_synology_completed_archive_moves.py"
PLAYBOOK = ROOT / "ansible/playbooks/diagnose-paperless-group-auto-nas-sender.yml"

spec = importlib.util.spec_from_file_location("group_collision_proof", PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class GroupCollisionArchiveProofTests(unittest.TestCase):
    def test_python_syntax_and_no_file_mutation_apis(self):
        src = PROBE.read_text()
        ast.parse(src)
        for banned in ("os.rename(", "os.unlink(", "os.replace(",
                       "os.chmod(", ".write_bytes(", ".write_text(",
                       "subprocess.Popen(", "subprocess.run(", "os.utime("):
            self.assertNotIn(banned, src)
        self.assertIn("LOCK_EX | LOCK_NB", src)
        self.assertIn("os.O_NOFOLLOW", src)
        self.assertIn("NO_SOURCE_CHANGED", src)
        self.assertIn("NO_RECEIPT_CHANGED", src)
        self.assertIn("NO_ARCHIVE_OR_PURGE", src)
        self.assertNotIn("print(source", src)
        self.assertNotIn("print(receipt", src)

    def test_exact_audited_previous_archive_and_pdf_are_mandatory(self):
        src = PROBE.read_text()
        self.assertIn("audit.inspect_events", src)
        self.assertIn("audit.inspect_pdf", src)
        self.assertIn("move._read_receipt", src)
        self.assertIn("move._validated_protected_scope", src)
        self.assertIn("sha256", src)
        self.assertIn("NEW_INODE_PRIOR_ARCHIVE_UNVERIFIED", src)
        self.assertIn("SAME_INODE_SAME_BYTES_DRIFT", src)

    def test_no_prior_archive_is_never_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            state = parent / "state"
            state.mkdir()
            folder = parent / "Familie"
            folder.mkdir()
            class FakeMove:
                JOURNAL_DIR = "journal"
                _check_dir = staticmethod(lambda *_args: os.open(
                    parent, os.O_RDONLY | os.O_DIRECTORY))
            class FakeAudit:
                inspect_events = staticmethod(lambda *_args: {})
                read_event = staticmethod(lambda *_args: None)
            self.assertFalse(probe.prior_archive_verified(
                state, folder, "Familie", "scan.pdf",
                {"sha256": "a"*64, "signature": [1, 2, 3, 4, 5]},
                move=FakeMove, audit=FakeAudit))

    def test_in_memory_auditor_no_deployment_and_privacy_mask(self):
        play = yaml.safe_load(PLAYBOOK.read_text())[0]
        matching = [t for t in play["tasks"]
                    if t.get("register") == "collision_archive_proof_diagnostic"]
        self.assertEqual(len(matching), 1)
        task = matching[0]
        self.assertIs(task["no_log"], True)
        self.assertIs(task["changed_when"], False)
        self.assertIs(task["failed_when"], False)
        self.assertEqual(task["delegate_to"], "localhost")
        stdin = task["ansible.builtin.command"]["stdin"]
        self.assertIn("types.ModuleType", stdin)
        self.assertIn("base64.b64decode", stdin)
        self.assertIn("audit_synology_completed_archive_moves.py", stdin)
        self.assertIn("diagnose_synology_group_collision_archive_proof.py", stdin)
        self.assertFalse("mkdir " in stdin)
        self.assertTrue(AUDITOR.is_file())

    def test_only_allowlisted_counts_are_displayed(self):
        raw = PLAYBOOK.read_text()
        self.assertIn("collision_archive_proof_diagnostic.stdout_lines", raw)
        self.assertIn("select('match', '^GROUP_ARCHIVE_PROOF ", raw)
        self.assertIn("GROUP_ARCHIVE_PROOF_UNAVAILABLE", raw)
        self.assertNotIn("debug:\n        var: collision_archive_proof_diagnostic", raw)


if __name__ == "__main__":
    unittest.main()
