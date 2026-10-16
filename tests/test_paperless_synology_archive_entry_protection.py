"""Unit tests: ACL risks and correct active same-device archive path audit."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    def test_protected_parent_admin_root_and_service_not_blocked(self):
        listing = sample(
            "[0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:0)\n"
            "[1] group:administrators@bergen.intern:allow:rwxpdDaARWc--:fd-- (level:0)\n"
            "[2] user:paperless-sync:allow:rwxpdDaARWc--:fd-- (level:0)\n"
            "[3] user:root:allow:rwxpdDaARWc--:fd-- (level:0)")
        self.assertEqual(m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"), [])


    def test_special_principals_and_spaced_level_supported(self):
        listing = sample(
            "[0] everyone::allow:--x----------:fd-- (level: 0)\n"
            "[1] owner::allow:rwxpdDaARWcCo:fd-- (level: 1)\n"
            "[2] system::allow:r-x---a-R-c--:fd-- (level:0)")
        parsed = m.parse_aces(listing)
        self.assertEqual([row[0] for row in parsed],
                         ["everyone", "owner", "system"])
        self.assertEqual(m.unsafe_parent_grants(parsed, "paperless-sync"), [])

    def test_everyone_delete_child_must_block(self):
        listing = sample(
            "[0] everyone::allow:rwxpdDaARWcCo:fd-- (level:0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [("everyone", "<special>")])

    def test_system_delete_child_must_block(self):
        listing = sample(
            "[0] system::allow:rwxpdDaARWc--:fd-- (level: 0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [("system", "<special>")])

    def test_unknown_special_or_injected_ace_denied(self):
        for line in (
            "[0] mystery::allow:rwxpdDaARWcCo:fd-- (level:0)",
            "[0] everyone:fake:allow:rwxpdDaARWcCo:fd-- (level:0)",
            "[0] user::allow:rwxpdDaARWcCo:fd-- (level:0)",
            "[0] user:alice:allow:rwxpdDaARWcCo:fd-- (level:0) junk",
            "[0] everyone::allow:rwxpdDaARWcCo:fd-- (level:0)\n"
            "[1] everyone::allow:UNKNOWN:fd-- (level:0)",
        ):
            with self.subTest(line=line), self.assertRaises(RuntimeError):
                m.parse_aces(sample(line))

    def test_special_deny_is_not_a_delete_allow(self):
        listing = sample(
            "[0] everyone::deny:rwxpdDaARWcCo:fd-- (level: 0)\n"
            "[1] system::allow:r-x---a-R-c--:fd-- (level:0)")
        self.assertEqual(
            m.unsafe_parent_grants(m.parse_aces(listing), "paperless-sync"),
            [])

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


    def test_only_deployed_sibling_archive_parents_are_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            group_root = base / "paperless-scan"
            private_root = base / "homes"
            group_root.mkdir()
            private_root.mkdir()
            sources = [
                (group_root / "scan-Eltern", "Eltern"),
                (group_root / "scan-Familie", "Familie"),
                (private_root / "scan-thomas", "Privat/thomas"),
                (private_root / "scan-nadja", "Privat/nadja"),
            ]
            for source, _ in sources:
                source.mkdir()
            mapping = {"Eltern": "paperless-scan",
                       "Familie": "paperless-scan",
                       "Privat/thomas": "homes",
                       "Privat/nadja": "homes"}
            worker = SimpleNamespace(
                SITE_BY_SCOPE=mapping,
                PROTECTED_ARCHIVE_DIR=".bergen-paperless-archive",
                _validated_protected_scope=lambda source, scope, uid:
                    (group_root if mapping[scope] == "paperless-scan"
                     else private_root) / ".bergen-paperless-archive" /
                    Path(*scope.split("/")))
            with patch.object(Path, "lstat", autospec=True) as mocked:
                # stat shape: only directory mode and stable same-device matter
                mocked.return_value = SimpleNamespace(st_mode=0o40700, st_dev=17)
                targets = m.protected_entry_targets(sources, 1024, worker)
            group_archive = group_root / ".bergen-paperless-archive"
            private_archive = private_root / ".bergen-paperless-archive"
            self.assertEqual(targets[group_root][1], "SITE_ROOT")
            self.assertEqual(targets[group_archive][1], "PROTECTED_ROOT")
            self.assertEqual(
                targets[group_archive / "Familie"][1], "PROTECTED_SCOPE")
            self.assertEqual(targets[private_root][1], "SITE_ROOT")
            self.assertEqual(
                targets[private_archive / "Privat"][1],
                "PROTECTED_INTERMEDIATE")
            self.assertEqual(
                targets[private_archive / "Privat/thomas"][1],
                "PROTECTED_SCOPE")
            self.assertEqual(len(targets), 9)
            self.assertFalse(any(".paperless-archive" == part
                                 for path in targets for part in path.parts))

    def test_archive_inside_scan_inbox_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            group_root = base / "paperless-scan"
            private_root = base / "homes"
            group_root.mkdir()
            private_root.mkdir()
            sources = [
                (group_root / "Eltern", "Eltern"),
                (group_root / "Familie", "Familie"),
                (private_root / "thomas", "Privat/thomas"),
                (private_root / "nadja", "Privat/nadja"),
            ]
            for source, _ in sources:
                source.mkdir()
            worker = SimpleNamespace(
                SITE_BY_SCOPE={"Eltern": "paperless-scan",
                               "Familie": "paperless-scan",
                               "Privat/thomas": "homes",
                               "Privat/nadja": "homes"},
                PROTECTED_ARCHIVE_DIR=".bergen-paperless-archive",
                _validated_protected_scope=lambda source, scope, uid:
                    source / ".bergen-paperless-archive" / scope)
            with self.assertRaisesRegex(
                    RuntimeError, "WRONG_ACTIVE_ARCHIVE_LOCATION"):
                m.protected_entry_targets(sources, 1024, worker)

    def test_existing_months_checked_and_unknown_entries_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "2026-10").mkdir(mode=0o700)
            def check(path, uid):
                return __import__("os").open(path, __import__("os").O_RDONLY |
                                            __import__("os").O_DIRECTORY)
            move = SimpleNamespace(_check_dir=check)
            device = folder.stat().st_dev
            self.assertEqual(
                m.existing_month_targets(folder, device, 1024, move),
                [folder / "2026-10"])
            (folder / "oops.pdf").write_text("synthetic")
            with self.assertRaisesRegex(
                    RuntimeError, "UNEXPECTED_PROTECTED_SCOPE_ENTRY"):
                m.existing_month_targets(folder, device, 1024, move)

    def test_audit_reports_effective_smb_not_tested(self):
        script = FILE.read_text()
        self.assertIn("DSM_SMB_EFFECTIVE_RENAME_NOT_TESTED", script)
        self.assertIn("ARCHIVE_COMMIT_NOT_AUTHORIZED", script)
        self.assertIn("existing_month_targets(", script)
        self.assertIn("get_aces(tool, path)", script)
        self.assertNotIn('source / ".paperless-archive"', script)


    def test_native_acl_failures_report_safe_error_categories_only(self):
        results = [
            ("SYNO: No ACL found for /secret/user", "NO_NATIVE_ACL_REPORTED"),
            ("operation not supported", "ACL_UNSUPPORTED_REPORTED"),
            ("Permission denied for /secret/user", "ACL_ACCESS_DENIED_REPORTED"),
            ("No such file or directory", "ACL_PATH_NOT_FOUND_REPORTED"),
            ("Unexpected native error for /secret/user",
             "UNCLASSIFIED_NATIVE_ACL_ERROR"),
        ]
        for error, expected in results:
            with self.subTest(error=expected):
                value = m.native_acl_failure_class(255, "", error)
                self.assertIn("RC_255_" + expected, value)
                self.assertNotIn("/secret/", value)
        with self.assertRaisesRegex(
                RuntimeError, "INVALID_NATIVE_ACL_FAILURE"):
            m.native_acl_failure_class(0, "", "")

    def test_native_acl_failed_command_does_not_publish_raw_principals(self):
        from types import SimpleNamespace
        message = "No ACL found for /volume1/homes/alice@example.invalid"
        completed = SimpleNamespace(returncode=255, stdout="", stderr=message)
        with patch.object(m.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "ACTIVE_ARCHIVE_NATIVE_ACL_QUERY_FAILED_RC_255_"
                    "NO_NATIVE_ACL_REPORTED") as captured:
                m.get_aces("/trusted/synoacltool", Path("/dummy"))
        self.assertNotIn("alice", str(captured.exception))

    def test_readonly_probe_contains_no_archive_mutations(self):
        code = FILE.read_text()
        for token in ("os.rename(", "os.replace(", "os.unlink(", ".unlink(",
                      "shutil.move(", "os.mkdir(", "subprocess.Popen("):
            self.assertNotIn(token, code)


if __name__ == "__main__":
    unittest.main()
