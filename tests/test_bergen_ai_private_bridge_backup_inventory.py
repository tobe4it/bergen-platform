"""Offline regression tests: no-write inventory of PVE-visible LXC backup metadata."""
import ast
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_private_bridge_backup_inventory.py"
PLAYBOOK = ROOT / "ansible/playbooks/audit-bergen-ai-private-bridge-backups-readonly.yml"
spec = importlib.util.spec_from_file_location("bridge_backup_inventory", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def run_simulated(stores, store_rows):
    values = [stores] + store_rows
    with mock.patch.object(m, "read_json", side_effect=values), mock.patch.object(m.time, "time", return_value=1900000000):
        output = io.StringIO()
        with redirect_stdout(output):
            m.execute_inventory()
        raw = output.getvalue().strip()
        assert raw.startswith(m.FRAME)
        return json.loads(raw[len(m.FRAME):])


class BackupInventoryTest(TestCase):
    def test_archive_name_and_guest_identity_strict(self):
        self.assertEqual(m.backup_id({"volid": "nfs:backup/vzdump-lxc-110-2026_10_18-04_00_00.tar.zst",
                                     "vmid": 110}), "110")
        self.assertEqual(m.backup_id({"volid": "nfs:backup/vzdump-lxc-126-2026_10_18-04_00_00.tar.gz",
                                     "vmid": "126"}), "126")
        self.assertEqual(m.backup_id({"volid": "nfs:backup/vzdump-lxc-126-2026_10_18-04_00_00.tar.zst",
                                     "vmid": 110}), None)
        self.assertEqual(m.backup_id({"volid": "nfs:backup/vzdump-qemu-110-2026_10_18-04_00_00.vma.zst"}), "")
        self.assertEqual(m.backup_id({"volid": "nfs:backup/vzdump-lxc-11-2026_10_18-04_00_00.tar.zst"}), "")
        self.assertEqual(m.backup_id({"volid": None}), None)

    def test_recent_and_old_backups_are_only_metadata(self):
        now = 1900000000
        stores = [{"storage": "mount", "active": 1}, {"storage": "local", "active": 1}]
        recent = {"volid": "mount:backup/vzdump-lxc-126-2026_10_18-04_00_00.tar.zst",
                  "ctime": now - 10000, "size": 12345, "vmid": 126}
        old = {"volid": "local:backup/vzdump-lxc-110-2026_09_18-04_00_00.tar.zst",
               "ctime": now - 15 * 86400, "size": 1200, "vmid": 110}
        report = run_simulated(stores, [[recent], [old]])
        self.assertEqual(report["STATUS"], "VISIBLE_STORAGES_SCANNED")
        self.assertEqual(report["CT110_BACKUPS"], "OLDER_METADATA_ONLY")
        self.assertEqual(report["CT126_BACKUPS"], "RECENT_METADATA_ONLY")
        self.assertEqual(report["ACTIVE_BACKUP_STORAGES"], 2)
        self.assertFalse(report["APPLY_AUTHORIZED"])
        self.assertEqual(report["ROLLBACK_CLEARANCE"], "NOT_PROVEN")
        self.assertEqual(report["RESTORE_TEST"], "NOT_ATTESTED")

    def test_missing_visible_archives_does_not_claim_no_backups_exist(self):
        report = run_simulated([{"storage": "local", "active": 1}], [[]])
        self.assertEqual(report["CT110_BACKUPS"], "NONE_IN_SCANNED_STORAGES")
        self.assertEqual(report["STORAGE_COVERAGE"], "VISIBLE_ONLY")

    def test_storage_query_error_preserves_partial_result_and_does_not_clear(self):
        now = 1900000000
        recent = {"volid": "a:backup/vzdump-lxc-126-2026_10_18-04_00_00.tar.zst",
                  "ctime": now - 30, "size": 1024}
        report = run_simulated([{"storage": "a", "active": True},
                                {"storage": "b", "active": False},
                                {"storage": "c", "active": True}], [[recent], None])
        self.assertEqual(report["STATUS"], "INVENTORY_PARTIAL")
        self.assertEqual(report["CT110_BACKUPS"], "UNVERIFIED")
        self.assertEqual(report["CT126_BACKUPS"], "RECENT_METADATA_ONLY")
        self.assertEqual(report["STORAGE_COVERAGE"], "INCOMPLETE")

    def test_invalid_or_oversized_input_never_proves_coverage(self):
        for items in (None, [{"storage": "bad/value", "active": 1}],
                      [{"storage": "a", "active": 1}] * 26):
            with mock.patch.object(m, "read_json", return_value=items):
                output = io.StringIO()
                with redirect_stdout(output):
                    m.execute_inventory()
            frame = json.loads(output.getvalue().strip()[len(m.FRAME):])
            self.assertEqual(frame["STATUS"], "INVENTORY_UNVERIFIED")
            self.assertFalse(frame["APPLY_AUTHORIZED"])
        self.assertIsNone(m.classify_items([{}], 1900000000))
        self.assertIsNone(m.classify_items([{}] * (m.MAX_ITEMS_PER_STORE + 1), 1900000000))

    def test_code_and_playbook_have_read_only_boundaries(self):
        source = SCRIPT.read_text()
        ast.parse(source)
        for banned in ("pct set", "vzdump --", "qmrestore", "pct restore",
                       "systemctl restart", "ifreload", "os.unlink",
                       "shutil.copy", "requests.", "urlopen", "pvesh set"):
            self.assertNotIn(banned, source)
        self.assertIn('APPLY_AUTHORIZED=False', source)
        self.assertIn('BACKUP_OPERATIONS="NONE"', source)
        play = yaml.safe_load(PLAYBOOK.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        commands = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        self.assertIn("not inventory_gate.APPLY_AUTHORIZED", PLAYBOOK.read_text())


if __name__ == "__main__":
    import unittest
    unittest.main()
