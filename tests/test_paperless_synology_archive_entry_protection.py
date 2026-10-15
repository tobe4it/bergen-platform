"""Unit tests: hidden archive entry protection risk in Synology DSM source ACEs."""
import importlib.util
import unittest
from pathlib import Path

FILE = (Path(__file__).resolve().parents[1] /
        "ansible/files/paperless/audit_synology_archive_entry_protection.py")
spec = importlib.util.spec_from_file_location("acl_risk", FILE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sample(ace):
    return ("ACL version: 1\nArchive: has_ACL,is_support_ACL\n"
            "Owner: [root(user)]\n---------------------\n"
            + ace + "\n")


class EntryProtectionTests(unittest.TestCase):
    def test_source_parent_admin_and_service_not_blocked(self):
        listing = sample(
            "[0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:0)\n"
            "[1] group:administrators@bergen.intern:allow:rwxpdDaARWc--:fd-- (level:0)\n"
            "[2] user:paperless-sync:allow:rwxpdDaARWc--:fd-- (level:0)")
        self.assertEqual(m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"), [])

    def test_family_group_delete_child_blocks(self):
        listing = sample(
            "? [1] group:Familie@bergen.intern:allow:rwxpdDaARWc--:fd-- (level:0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [("group", "Familie@bergen.intern")])

    def test_parent_group_delete_child_blocks(self):
        listing = sample(
            "? [1] group:Eltern@bergen.intern:allow:rwxpdDaARWc--:fd-- (level:0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [("group", "Eltern@bergen.intern")])

    def test_readonly_group_does_not_block(self):
        listing = sample(
            "? [1] group:Familie@bergen.intern:allow:r-x---a-R-c--:---- (level:0)")
        self.assertEqual(m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"), [])

    def test_unknown_nonadmin_user_with_write_execute_blocks(self):
        listing = sample(
            "[4] user:random:allow:rwx---a-R-c--:---- (level:0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [("user", "random")])

    def test_explicit_deny_not_assumed_to_grant(self):
        listing = sample(
            "[4] group:Familie@bergen.intern:deny:rwxpdDaARWc--:fd-- (level:0)")
        self.assertEqual(m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"), [])

    def test_malformed_native_acl_entry_rejected(self):
        listing = sample(
            "[1] group:Familie@bergen.intern:allow:MALFORMED:fd-- (level:0)")
        with self.assertRaisesRegex(RuntimeError, "UNPARSEABLE_ACL_ACE"):
            m.parse_aces(listing)

    def test_missing_native_aces_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "NO_ACL_ENTRIES"):
            m.parse_aces("ACL version: 1\n")

    def test_deleted_directory_permission_flag_blocks(self):
        listing = sample(
            "[2] group:test:allow:r-x-d-a-R-c--:---- (level:0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [("group", "test")])

    def test_readonly_probe_contains_no_archive_mutations(self):
        code = FILE.read_text()
        for token in ("os.rename(", "os.replace(", "os.unlink(", ".unlink(",
                      "shutil.move(", "os.mkdir(", "subprocess.Popen("):
            self.assertNotIn(token, code)


if __name__ == "__main__":
    unittest.main()
