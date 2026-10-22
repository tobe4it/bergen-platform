"""Offline checks for read-only CT110 compressed stream and TAR verification."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/verify_ct110_archive_stream_readonly.py"
PLAY = ROOT / "ansible/playbooks/verify-bergen-ai-ct110-archive-stream-readonly.yml"
spec = importlib.util.spec_from_file_location("ct110_archive_stream", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

NAME = "vzdump-lxc-110-2026_10_20-06_15_00.tar.zst"
VOLID = "bergen-synology-backup:backup/" + NAME


class CT110ArchiveStreamTests(TestCase):
    def test_only_one_exact_archive_name_and_storage(self):
        with mock.patch.object(a, "metadata_command", return_value=[
            {"volid": VOLID, "size": 123456}
        ]):
            self.assertEqual(a.unique_archive_metadata(), (NAME, 123456))
        for invalid in (
                [{"volid": VOLID, "size": 0}],
                [{"volid": VOLID, "size": "123456"}],
                [{"volid": VOLID, "size": 123456},
                 {"volid": VOLID, "size": 123456}],
                [{"volid": "../:backup/" + NAME, "size": 123456}],
                [{"volid": "elsewhere:backup/" + NAME, "size": 123456}],
                [{"volid": "bergen-synology-backup:backup/vzdump-lxc-110-xxx.tar.zst",
                  "size": 123456}],
                [{"volid": VOLID[:-4] + ".gz", "size": 123456}],
                [{"volid": VOLID, "size": True}],
        ):
            with self.subTest(invalid=invalid), mock.patch.object(
                    a, "metadata_command", return_value=invalid):
                self.assertIsNone(a.unique_archive_metadata())

    def test_storage_requires_actual_nfs_and_proxmox_backup_content(self):
        fs = {"filesystems": [{"target": str(a.MOUNT), "fstype": "nfs4"}]}
        active = {"active": 1, "content": "backup,images"}
        with mock.patch.object(a, "metadata_command", side_effect=[fs, active]):
            self.assertTrue(a.storage_active())
        with mock.patch.object(a, "metadata_command",
                               side_effect=[{"filesystems": [
                                   {"target": str(a.MOUNT), "fstype": "ext4"}]}, active]):
            self.assertFalse(a.storage_active())
        with mock.patch.object(a, "metadata_command",
                               side_effect=[fs, {"active": 0, "content": "backup"}]):
            self.assertFalse(a.storage_active())

    def test_stream_and_tar_success_without_writes_or_restore(self):
        with (mock.patch.object(a, "storage_active", return_value=True),
              mock.patch.object(a, "ct110_running", return_value=True),
              mock.patch.object(a, "unique_archive_metadata", return_value=(NAME, 123456)),
              mock.patch.object(a, "safe_archive", return_value=(
                  Path("/mnt/pve/bergen-synology-backup/dump") / NAME,
                  (1, 22, 123456, 333))),
              mock.patch.object(a, "stream_check", return_value=True) as stream,
              mock.patch.object(a, "stat_unchanged", return_value=True)):
            result = a.check()
        self.assertEqual(result["STATUS"], "COMPRESSED_STREAM_AND_TAR_READABLE")
        self.assertEqual(result["ZSTD_STREAM_CHECK"], "PASS")
        self.assertEqual(result["TAR_READ_CHECK"], "PASS")
        self.assertEqual(result["CT110_STATE_AFTER"], "RUNNING")
        calls = [call.args[0] for call in stream.call_args_list]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:4], ["zstd", "-q", "-t", "--"])
        self.assertEqual(calls[1][:3], ["tar", "-I", "zstd"])
        self.assertEqual(calls[1][3], "-tf")

    def test_invalid_archive_does_not_read_bytes(self):
        with (mock.patch.object(a, "storage_active", return_value=True),
              mock.patch.object(a, "ct110_running", return_value=True),
              mock.patch.object(a, "unique_archive_metadata", return_value=None),
              mock.patch.object(a, "stream_check") as stream):
            result = a.check()
            stream.assert_not_called()
            self.assertEqual(result["STATUS"], "REVIEW_REQUIRED")
        with (mock.patch.object(a, "storage_active", return_value=False),
              mock.patch.object(a, "stream_check") as stream):
            result = a.check()
            self.assertEqual(result["VERIFY_STAGE"], "PRECONDITIONS")
            stream.assert_not_called()

    def test_zstd_failure_or_archive_change_aborts_before_tar(self):
        with (mock.patch.object(a, "storage_active", return_value=True),
              mock.patch.object(a, "ct110_running", return_value=True),
              mock.patch.object(a, "unique_archive_metadata", return_value=(NAME, 120)),
              mock.patch.object(a, "safe_archive", return_value=(Path("/tmp/archive"), (1, 2, 120, 3))),
              mock.patch.object(a, "stream_check", return_value=False) as stream):
            result = a.check()
            self.assertEqual(result["VERIFY_STAGE"], "ZSTD_STREAM")
            self.assertEqual(stream.call_count, 1)
        with (mock.patch.object(a, "storage_active", return_value=True),
              mock.patch.object(a, "ct110_running", return_value=True),
              mock.patch.object(a, "unique_archive_metadata", return_value=(NAME, 120)),
              mock.patch.object(a, "safe_archive", return_value=(Path("/tmp/archive"), (1, 2, 120, 3))),
              mock.patch.object(a, "stream_check", return_value=True) as stream,
              mock.patch.object(a, "stat_unchanged", return_value=False)):
            result = a.check()
            self.assertEqual(result["VERIFY_STAGE"], "ARCHIVE_CHANGED_DURING_ZSTD")
            self.assertEqual(stream.call_count, 1)

    def test_tar_failure_or_postcheck_change_is_not_success(self):
        with (mock.patch.object(a, "storage_active", return_value=True),
              mock.patch.object(a, "ct110_running", return_value=True),
              mock.patch.object(a, "unique_archive_metadata", return_value=(NAME, 120)),
              mock.patch.object(a, "safe_archive", return_value=(Path("/tmp/archive"), (1, 2, 120, 3))),
              mock.patch.object(a, "stream_check", side_effect=[True, False]),
              mock.patch.object(a, "stat_unchanged", return_value=True)):
            result = a.check()
            self.assertEqual(result["TAR_READ_CHECK"], "FAIL_OR_UNAVAILABLE")
            self.assertEqual(result["STATUS"], "CHECK_FAILED_OR_UNAVAILABLE")
        with (mock.patch.object(a, "storage_active", return_value=True),
              mock.patch.object(a, "ct110_running", return_value=True),
              mock.patch.object(a, "unique_archive_metadata", return_value=(NAME, 120)),
              mock.patch.object(a, "safe_archive", return_value=(Path("/tmp/archive"), (1, 2, 120, 3))),
              mock.patch.object(a, "stream_check", return_value=True),
              mock.patch.object(a, "stat_unchanged", side_effect=[True, False])):
            result = a.check()
            self.assertEqual(result["STATUS"], "REVIEW_REQUIRED")
            self.assertEqual(result["FILE_STABLE_AFTER_CHECK"], "NO")

    def test_script_has_no_mutating_subprocess_and_play_is_no_log(self):
        ast.parse(SCRIPT.read_text())
        source = SCRIPT.read_text()
        self.assertIn('RESTORE_TEST="NOT_ATTESTED"', source)
        self.assertIn("BACKUP_RETRIED=False", source)
        tree = ast.parse(source)
        subprocess_invocations = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("run", "Popen")]
        self.assertGreaterEqual(len(subprocess_invocations), 2)
        self.assertNotIn('["vzdump"', source)
        self.assertNotIn('["pct", "stop"', source)
        self.assertNotIn('["pct", "start"', source)
        self.assertNotIn('["pct", "restore"', source)
        self.assertNotIn("tar -x", source)
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertFalse(play["gather_facts"])
        self.assertEqual(len([x for x in play["tasks"] if "ansible.builtin.command" in x]), 1)
        t = next(x for x in play["tasks"] if "ansible.builtin.command" in x)
        self.assertFalse(t["changed_when"])
        self.assertTrue(t["no_log"])
        self.assertGreaterEqual(t["async"], 10800)
        self.assertIn("RESTORE_TEST=NOT_ATTESTED", PLAY.read_text())
