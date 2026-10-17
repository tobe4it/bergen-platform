"""Stage-only tests for protected process argv and readonly receiver execution."""
import hashlib
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SRC))

import synology_receipt_v2_store as store
import v2_process_preflight as stage

PDF = b"%PDF-1.4\n1 0 obj\n(offline)\nendobj\n%%EOF\n"
SHA = hashlib.sha256(PDF).hexdigest()
SIG = [202, 303, len(PDF), 404, 505]


class ProcessPreflightTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.prepared = store.prepared_record(
            "Familie", "Gescanntes Dokument.pdf", SHA, SIG, "a" * 32)
        name = self.prepared["destination"].split("/")[-1]
        self.snapshot = self.tmp / name
        self.snapshot.write_bytes(PDF)
        self.snapshot.chmod(0o600)
        self.identity = self.tmp / "id_ed25519"
        self.identity.write_text("fixture-key")
        self.identity.chmod(0o600)
        self.known = self.tmp / "known_hosts"
        self.known.write_text("venombox ssh-ed25519 AAAAfixture")
        self.known.chmod(0o600)
        # A checked-out Git worktree can inherit a group-writable umask.
        # Test the strict production mode guard using a controlled 0600
        # verifier fixture rather than relaxing the guard itself.
        self.verifier = self.tmp / "verify_receiver_v2_staging.py"
        self.verifier.write_bytes((SRC / "verify_receiver_v2_staging.py").read_bytes())
        self.verifier.chmod(0o600)
        self.called = []

    def plan(self, **kw):
        return stage.build_rsync_plan(
            kw.get("prepared", self.prepared),
            kw.get("snapshot", self.snapshot),
            kw.get("destination", "paperless-ingest@paperless.example.net"),
            kw.get("identity", self.identity),
            kw.get("known_hosts", self.known))

    def receiver_stdout(self, prepared=None):
        p = prepared or self.prepared
        scope, name = p["destination"].rsplit("/", 1)
        size = p["signature"][2]
        binding = hashlib.sha256(
            (scope + "\0" + name + "\0" + p["sha256"] + "\0" + str(size))
            .encode("utf-8")
        ).hexdigest()
        return ("\n".join([
            "RECEIVER_BINDING " + binding,
            "RECEIVER_SHA256 " + p["sha256"],
            "RECEIVER_BYTES " + str(size),
            "RECEIVER_POINT_IN_TIME_VERIFIED",
            "NEW_FILE_NOT_ATTESTED",
            "PAPERLESS_IMPORT_NOT_ATTESTED",
            "SENT_NOT_AUTHORIZED",
            "SOURCE_DELETE_NOT_AUTHORIZED",
            "NO_FILES_CHANGED",
        ]) + "\n").encode()

    def mock_remote(self, results=None):
        response = list(results or [
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n", b""),
            (0, b"status: running\n", b""),
            (0, self.receiver_stdout(), b""),
        ])

        def run(argv, **kwargs):
            self.called.append((argv, kwargs))
            if not response:
                raise AssertionError("unexpected extra remote subprocess")
            rc, out, err = response.pop(0)
            return subprocess.CompletedProcess(argv, rc, out, err)
        return run

    def check_remote(self, **kw):
        # Patch only the module location, not its file-validation logic.
        # The read-only SSH calls still use the same audited verifier bytes.
        with patch.object(stage, "__file__", str(self.tmp / "v2_process_preflight.py")):
            return stage.run_readonly_receiver(
                kw.get("prepared", self.prepared),
                kw.get("target", "ansible@venombox"),
                kw.get("identity", self.identity),
                kw.get("known_hosts", self.known))

    def test_rsync_argv_immutable_and_not_executed(self):
        with patch.object(stage.subprocess, "run",
                          side_effect=AssertionError("must not run")):
            cmd = self.plan()
        self.assertIsInstance(cmd, tuple)
        self.assertEqual(cmd[0], "rsync")
        self.assertIn("--ignore-existing", cmd)
        self.assertIn("--chmod=F600", cmd)
        self.assertIn("--out-format=%i %n", cmd)
        self.assertEqual(cmd[-2], str(self.snapshot))
        self.assertEqual(cmd[-1], "paperless-ingest@paperless.example.net:Familie/")
        self.assertEqual(cmd[-3], "--")
        ssh = shlex.split(cmd[cmd.index("-e") + 1])
        self.assertIn("StrictHostKeyChecking=yes", ssh)
        self.assertIn("IdentitiesOnly=yes", ssh)
        self.assertIn("UserKnownHostsFile=" + str(self.known), ssh)
        self.assertNotIn("StrictHostKeyChecking=no", ssh)

    def test_rsync_requires_exact_nonce_bound_basename(self):
        renamed = self.tmp / "frozen.pdf"
        renamed.write_bytes(PDF)
        renamed.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_NAME_NOT_BOUND"):
            self.plan(snapshot=renamed)

    def test_rsync_rejects_changed_snapshot_bytes(self):
        self.snapshot.write_bytes(PDF.replace(b"offline", b"changed"))
        with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_NOT_BOUND"):
            self.plan()

    def test_rsync_rejects_size_mismatch(self):
        self.snapshot.write_bytes(PDF + b"changed")
        with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_NOT_BOUND"):
            self.plan()

    def test_rsync_rejects_snapshot_symlink(self):
        old = self.tmp / "safe"
        self.snapshot.rename(old)
        self.snapshot.symlink_to(old)
        with self.assertRaises(RuntimeError):
            self.plan()

    def test_rsync_rejects_snapshot_hardlink(self):
        os.link(self.snapshot, self.tmp / "second")
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_TRUSTED_FILE"):
            self.plan()

    def test_rsync_rejects_public_snapshot(self):
        self.snapshot.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_TRUSTED_FILE"):
            self.plan()

    def test_rsync_rejects_unbound_prepared(self):
        fake = dict(self.prepared, incarnation_nonce="b" * 32)
        with self.assertRaisesRegex(ValueError, "INVALID_PREPARED"):
            self.plan(prepared=fake)

    def test_rsync_rejects_unsafe_ssh_target(self):
        for name in ("user@host;touch /tmp/evil", "-oProxyCommand=evil",
                     "user@host/name", "bad hostname", "user@@host"):
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "INVALID_PINNED_SSH_TARGET"):
                self.plan(destination=name)

    def test_ssh_private_key_permissions_enforced(self):
        self.identity.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_TRUSTED_FILE"):
            self.plan()

    def test_ssh_known_hosts_symlink_rejected(self):
        copy = self.tmp / "known-elsewhere"
        self.known.rename(copy)
        self.known.symlink_to(copy)
        with self.assertRaises(RuntimeError):
            self.plan()

    def test_ssh_private_known_hosts_accepted(self):
        self.known.chmod(0o644)
        cmd = self.plan()
        self.assertTrue(cmd)

    def test_valid_readonly_receiver_has_three_captured_commands(self):
        with patch.object(stage.subprocess, "run",
                          side_effect=self.mock_remote()):
            result = self.check_remote()
        self.assertEqual(len(self.called), 3)
        for command, opts in self.called:
            self.assertEqual(command[0], "ssh")
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("BatchMode=yes", command)
            self.assertIn("IdentitiesOnly=yes", command)
            self.assertIn("UserKnownHostsFile=" + str(self.known), command)
            self.assertIn("ansible@venombox", command)
            self.assertFalse(opts["shell"])
            self.assertFalse(opts["check"])
            self.assertGreater(opts["timeout"], 0)
        self.assertIsNone(self.called[0][1]["input"])
        self.assertIsNone(self.called[1][1]["input"])
        commands = [shlex.split(x[0][-1]) for x in self.called]
        self.assertEqual(commands[0], ["sudo", "-n", "/usr/sbin/pct", "config", "126"])
        self.assertEqual(commands[1], ["sudo", "-n", "/usr/sbin/pct", "status", "126"])
        self.assertEqual(commands[2][:13], [
            "sudo", "-n", "/usr/sbin/pct", "exec", "126", "--", "/usr/sbin/runuser",
            "-u", "paperless-ingest", "--", "/usr/bin/python3", "-", "Familie"])
        self.assertEqual(commands[2][-3:],
                         [self.snapshot.name, SHA, str(len(PDF))])
        self.assertIn(b"RECEIVER_BINDING", self.called[2][1]["input"])
        self.assertEqual(result["receiver_sha256"], SHA)
        self.assertTrue(result["ssh_strict_hostkey_enforced"])
        self.assertTrue(result["receiver_process_checked"])
        self.assertFalse(result["sender_attempt_authenticated"])
        self.assertFalse(result["sent_authorized"])
        self.assertFalse(result["source_delete_authorized"])

    def test_verifier_group_writable_is_rejected_before_any_ssh(self):
        self.verifier.chmod(0o664)
        with patch.object(stage.subprocess, "run",
                          side_effect=AssertionError("unsafe verifier must not run SSH")):
            with self.assertRaisesRegex(RuntimeError, "UNSAFE_TRUSTED_FILE"):
                self.check_remote()
        self.assertEqual(self.called, [])

    def test_verifier_symlink_is_rejected_before_any_ssh(self):
        safe = self.tmp / "legitimate"
        self.verifier.rename(safe)
        self.verifier.symlink_to(safe)
        with patch.object(stage.subprocess, "run",
                          side_effect=AssertionError("symlink verifier must not run SSH")):
            with self.assertRaisesRegex(RuntimeError, "UNSAFE_TRUSTED_FILE"):
                self.check_remote()

    def test_wrong_guest_blocks_before_status(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: other\nunprivileged: 1\n", b"")])):
            with self.assertRaisesRegex(RuntimeError, "WRONG_OR_UNSAFE_RECEIVER_GUEST"):
                self.check_remote()
        self.assertEqual(len(self.called), 1)

    def test_privileged_guest_blocks(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 0\n", b"")])):
            with self.assertRaisesRegex(RuntimeError, "WRONG_OR_UNSAFE_RECEIVER_GUEST"):
                self.check_remote()

    def test_unconfined_guest_blocks(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n"
                b"lxc.apparmor.profile: unconfined\n", b"")])):
            with self.assertRaisesRegex(RuntimeError, "WRONG_OR_UNSAFE_RECEIVER_GUEST"):
                self.check_remote()

    def test_stopped_guest_blocks_before_receiver(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n", b""),
            (0, b"status: stopped\n", b"")])):
            with self.assertRaisesRegex(RuntimeError, "RECEIVER_GUEST_NOT_RUNNING"):
                self.check_remote()
        self.assertEqual(len(self.called), 2)

    def test_ssh_nonzero_exit_blocks(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (255, b"", b"host key verification failed")])):
            with self.assertRaisesRegex(RuntimeError, "REMOTE_PCT_AUDIT_FAILED"):
                self.check_remote()
        self.assertEqual(len(self.called), 1)

    def test_ssh_stderr_blocks_even_with_exit_zero(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n", b"warning")])):
            with self.assertRaisesRegex(RuntimeError, "REMOTE_PCT_AUDIT_FAILED"):
                self.check_remote()

    def test_receiver_nonzero_exit_blocks(self):
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n", b""),
            (0, b"status: running\n", b""),
            (1, b"", b"failure")])):
            with self.assertRaisesRegex(RuntimeError, "REMOTE_PCT_AUDIT_FAILED"):
                self.check_remote()

    def test_receiver_fake_digest_is_rejected(self):
        broken = self.receiver_stdout().replace(SHA.encode(), b"f" * 64)
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n", b""),
            (0, b"status: running\n", b""),
            (0, broken, b"")])):
            with self.assertRaisesRegex(ValueError, "RECEIVER_PROOF_IDENTITY"):
                self.check_remote()

    def test_receiver_missing_negative_gate_is_rejected(self):
        broken = self.receiver_stdout().replace(b"SENT_NOT_AUTHORIZED\n", b"")
        with patch.object(stage.subprocess, "run", side_effect=self.mock_remote([
            (0, b"hostname: bergen-paperless\nunprivileged: 1\n", b""),
            (0, b"status: running\n", b""),
            (0, broken, b"")])):
            with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_REPEATED"):
                self.check_remote()

    def test_receiver_timeout_is_not_retried(self):
        with patch.object(stage.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired(["ssh"], 45)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.check_remote()
        self.assertEqual(len(self.called), 0)

    def test_no_remote_subprocess_for_invalid_ssh_files(self):
        self.identity.chmod(0o666)
        with patch.object(stage.subprocess, "run",
                          side_effect=AssertionError("bad config must not run")):
            with self.assertRaisesRegex(RuntimeError, "UNSAFE_TRUSTED_FILE"):
                self.check_remote()

    def test_no_sender_or_sent_integration(self):
        code = (SRC / "v2_process_preflight.py").read_text()
        self.assertNotIn("if __name__ == '__main__'", code)
        self.assertNotIn('if __name__ == "__main__"', code)
        self.assertNotIn("publish_event(", code)
        self.assertNotIn("sent_record(", code)
        self.assertNotIn("os.unlink(", code)
        self.assertNotIn("os.remove(", code)
        sender = (SRC / "synology_scan_sync.py").read_text()
        self.assertNotIn("v2_process_preflight", sender)


if __name__ == "__main__":
    unittest.main()
