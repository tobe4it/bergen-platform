"""Read-only and privacy-safe diagnosis after a group timer abort."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/diagnose-paperless-group-auto-nas-sender.yml"
MODULE = ROOT / "ansible/files/paperless/diagnose_synology_watcher_processes.py"
spec = importlib.util.spec_from_file_location("watch_process_inspector", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class GroupAutoDiagnosticsTests(unittest.TestCase):
    def test_safe_read_only_diagnosis_and_no_log(self):
        raw = PLAY.read_text()
        play = yaml.safe_load(raw)[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertIn("diagnos", play["name"].lower())
        private = [t for t in play["tasks"] if t.get("register")]
        self.assertEqual(
            {t["register"] for t in private},
            {"sender_audit_diagnostic", "watcher_process_diagnostic",
             "source_mismatch_diagnostic", "collision_archive_proof_diagnostic"},
        )
        for task in private:
            self.assertIs(task["no_log"], True)
            self.assertIs(task["changed_when"], False)
            self.assertIs(task["failed_when"], False)
            self.assertEqual(task["delegate_to"], "localhost")
            self.assertEqual(task["ansible.builtin.command"]["argv"][0], "ssh")
            self.assertIn("sudo -n -u", task["ansible.builtin.command"]["argv"][-1])
        self.assertIn("audit_synology_archive_candidates.py", raw)
        self.assertIn("diagnose_synology_watcher_processes.py", raw)
        self.assertIn("diagnose_synology_v1_receipt_mismatches.py", raw)
        self.assertIn("diagnose_synology_group_collision_archive_proof.py", raw)
        self.assertIn("audit_synology_completed_archive_moves.py", raw)
        self.assertIn("NEW_INODE_PRIOR_ARCHIVE_VERIFIED", raw)
        self.assertNotIn("debug:\n        var: sender_audit_diagnostic", raw)
        self.assertNotIn("debug:\n        var: watcher_process_diagnostic", raw)
        self.assertNotIn("ignore_errors:", raw)

    def test_all_published_errors_are_explicit_allowlist(self):
        raw = PLAY.read_text()
        self.assertIn("SOURCE_NOT_CONFIRMED_SENT", raw)
        self.assertIn("SOURCE_RECEIPT_MISMATCH", raw)
        self.assertIn("SOURCE_CHANGED_OR_HASH_MISMATCH", raw)
        self.assertIn("UNCLASSIFIED_ERROR", raw)
        self.assertIn("(?m)^", raw)
        self.assertNotIn("sender_audit_diagnostic.stderr }}", raw)
        self.assertNotIn("sender_audit_diagnostic.stdout }}", raw)

    def test_process_status_uses_only_known_absolute_script_and_uid(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            proc = base / "proc"
            proc.mkdir()
            parent = base / "paperless"
            (parent / "bin").mkdir(parents=True)
            for i, (script, args) in enumerate((
                ("synology_inotify_watch.py", ("--watch", "--commit")),
                ("synology_watcher_supervisor.py", ("--boot",)),
            )):
                entry = proc / str(100 + i)
                entry.mkdir()
                (entry / "cmdline").write_bytes(
                    b"/usr/bin/python3\0" +
                    os.fsencode(str(parent / "bin" / script)) +
                    b"\0" + b"\0".join(x.encode() for x in args) + b"\0")
            self.assertEqual(mod.is_running(
                parent, "synology_inotify_watch.py",
                ("--watch", "--commit"), os.geteuid(), proc), 1)
            self.assertEqual(mod.is_running(
                parent, "synology_watcher_supervisor.py",
                ("--boot",), os.geteuid(), proc), 1)
            self.assertEqual(mod.is_running(
                parent, "synology_inotify_watch.py",
                ("--probe",), os.geteuid(), proc), 0)

    def test_watcher_script_has_no_mutation_or_private_output(self):
        raw = MODULE.read_text()
        self.assertIn('Path("/proc")', raw)
        self.assertIn("WATCHER_PROCESS_STATE=", raw)
        self.assertIn("SENDER_ACTIVATION_GATE=", raw)
        self.assertNotIn("subprocess.run", raw)
        self.assertNotIn("os.unlink", raw)
        self.assertNotIn("os.rename", raw)
        self.assertNotIn("print(args", raw)


if __name__ == "__main__":
    unittest.main()
