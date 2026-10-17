"""Synthetic tests for NAS effective LOCAL (not SMB) archive access audit."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "ansible/files/paperless"
spec = importlib.util.spec_from_file_location(
    "effective_archive_access",
    BASE / "audit_synology_effective_archive_access.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ALLOW = {"list": True, "write_access": True}
DENY = {"list": False, "write_access": False}


class EffectiveArchiveAccessTests(unittest.TestCase):
    def test_two_real_explicit_nss_names_required(self):
        self.assertEqual(
            m.parse_names('["thomas@bergen.intern","nadja@bergen.intern"]'),
            ["thomas@bergen.intern", "nadja@bergen.intern"])

    def test_missing_duplicate_or_too_many_names_refused(self):
        for value in ([], ["a"], ["a", "a"], ["a"]*9, "a",
                      ["a", None], ["a", "x/y"], ["a", "--root"],
                      ["a", "x;rm"], ["a", "x\n"], ["a", ""]):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                m.parse_names(json.dumps(value))

    def test_only_valid_probe_schema_accepted(self):
        self.assertEqual(m.parse_probe(json.dumps(ALLOW)), ALLOW)
        self.assertEqual(m.parse_probe(json.dumps(DENY)), DENY)
        for value in ({}, {"list": True, "write_access": 1},
                      {"list": True, "write_access": False, "other": True},
                      {"list": "false", "write_access": False},
                      None, []):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                m.parse_probe(json.dumps(value))

    def test_all_three_owner_scopes_and_negative_identities_pass(self):
        expected = m.verdict([ALLOW]*3, [[DENY]*3, [DENY]*3])
        self.assertEqual(expected, [
            "ARCHIVE_LOCAL_OWNER_ACCESS_VERIFIED",
            "ARCHIVE_LOCAL_NEGATIVE_IDENTITIES_DENIED 2",
            "SMB_EFFECTIVE_ACCESS_NOT_TESTED",
            "ARCHIVE_COMMIT_NOT_AUTHORIZED",
            "NO_FILES_CHANGED",
        ])

    def test_owner_denied_any_directory_blocks(self):
        for i in range(3):
            owner = [ALLOW]*3
            owner[i] = DENY
            with self.subTest(index=i), self.assertRaisesRegex(
                    RuntimeError, "SYNC_OWNER_ARCHIVE_ACCESS_BLOCKED"):
                m.verdict(owner, [[DENY]*3, [DENY]*3])

    def test_nonowner_read_or_write_permission_blocks(self):
        for value in ({"list": True, "write_access": False},
                      {"list": False, "write_access": True},
                      ALLOW):
            with self.subTest(value=value), self.assertRaisesRegex(
                    RuntimeError, "NONOWNER_ARCHIVE_ACCESS_NOT_DENIED"):
                m.verdict([ALLOW]*3, [[DENY, value, DENY], [DENY]*3])

    def test_missing_negative_subject_fails(self):
        with self.assertRaisesRegex(RuntimeError, "NONOWNER_ARCHIVE_ACCESS_NOT_DENIED"):
            m.verdict([ALLOW]*3, [[DENY]*3])

    def test_no_mutating_probes_or_auto_selection(self):
        source = (BASE / "audit_synology_effective_archive_access.py").read_text()
        playbook = (
            BASE.parent.parent / "playbooks" /
            "audit-paperless-synology-effective-archive-access.yml").read_text()
        for banned in ("os.rename(", "os.replace(", "os.unlink(", "os.mkdir(",
                       "os.chmod(", "os.chown(", "os.rmdir(", "os.open(path, os.O_CREAT",
                       "touch(", "os.link(", "renameat2(", "os.truncate("):
            self.assertNotIn(banned, source)
        self.assertNotIn("archive-move.paperless-scan.enabled", source)
        self.assertIn("SMB_EFFECTIVE_ACCESS_NOT_TESTED", source)
        self.assertIn("no_log: true", playbook)
        self.assertIn("changed_when: false", playbook)
        self.assertIn("ARCHIVE_COMMIT_NOT_AUTHORIZED", playbook)


if __name__ == "__main__":
    unittest.main()
