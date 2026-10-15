"""Pure checks for read-only protected NAS archive-parent candidate discovery."""
import importlib.util
import stat
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE = (Path(__file__).resolve().parents[1] /
          "ansible/files/paperless/audit_synology_protected_archive_candidates.py")
spec = importlib.util.spec_from_file_location("archive_candidate_audit", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def st(uid=0, mode=0o755, dev=1048641, kind=stat.S_IFDIR):
    return SimpleNamespace(st_uid=uid, st_mode=kind | mode, st_dev=dev)


def acl(rows, rc=0):
    return subprocess.CompletedProcess(["synoacltool"], rc, stdout=rows, stderr="")


def line(role, principal, perms, effect="allow"):
    return ("? [0] " + role + ":" + principal + ":" + effect
            + ":" + perms + ":fd-- (level:0)\n")


class ProtectedArchiveCandidateTests(unittest.TestCase):
    def test_parent_without_obvious_delete_grants(self):
        listing = (line("group", "administrators", "rwxpdDaARWc--")
                   + line("group", "Familie@bergen.intern", "r-x---a-R-c--")
                   + line("user", "paperless-sync", "rwxpdDaARWc--"))
        self.assertEqual(
            audit.evaluate_parent(st(), acl(listing), "paperless-sync"),
            ("NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT", []))

    def test_family_and_parent_full_access_rejected(self):
        for group in ("Familie@bergen.intern", "Eltern@bergen.intern"):
            listing = line("group", group, "rwxpdDaARWc--")
            with self.subTest(group=group):
                status, bad = audit.evaluate_parent(st(), acl(listing), "paperless-sync")
                self.assertEqual(status, "PARENT_HAS_NONADMIN_DELETE_GRANTS")
                self.assertEqual(bad, ["group:" + group])

    def test_existing_named_home_user_write_rejected(self):
        listing = line("user", "thomas@bergen.intern", "rwxpdDaARWc--")
        status, bad = audit.evaluate_parent(st(), acl(listing), "paperless-sync")
        self.assertEqual(status, "PARENT_HAS_NONADMIN_DELETE_GRANTS")
        self.assertEqual(bad, ["user:thomas@bergen.intern"])

    def test_root_admin_and_service_full_access_accepted(self):
        listing = (line("group", "administrators", "rwxpdDaARWc--")
                   + line("group", "administrators@bergen.intern", "rwxpdDaARWc--")
                   + line("user", "root", "rwxpdDaARWc--")
                   + line("user", "paperless-sync", "rwxpdDaARWc--"))
        self.assertEqual(
            audit.evaluate_parent(st(), acl(listing), "paperless-sync"),
            ("NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT", []))

    def test_non_root_owned_candidate_parent_rejected(self):
        listing = line("group", "administrators", "rwxpdDaARWc--")
        self.assertEqual(
            audit.evaluate_parent(st(uid=1025), acl(listing), "paperless-sync")[0],
            "UNSAFE_UNOWNED_PARENT")

    def test_posix_parent_root_nongroup_writable_allowed_for_review(self):
        for mode in (0o700, 0o755, 0o711):
            with self.subTest(mode=mode):
                status, _ = audit.evaluate_parent(
                    st(mode=mode),
                    subprocess.CompletedProcess(["synoacltool"], 255,
                        "(synoacltool.c, 596)It's Linux mode\n", ""),
                    "paperless-sync")
                self.assertEqual(status, "ROOT_POSIX_PARENT_NO_GROUP_WRITE")

    def test_posix_parent_group_or_world_writable_rejected(self):
        for mode in (0o777, 0o775, 0o770, 0o757):
            with self.subTest(mode=mode):
                status, _ = audit.evaluate_parent(
                    st(mode=mode),
                    subprocess.CompletedProcess(["synoacltool"], 255,
                        "(synoacltool.c, 596)It's Linux mode\n", ""),
                    "paperless-sync")
                self.assertEqual(status, "POSIX_PARENT_WRITABLE_BY_OTHERS")

    def test_unknown_synology_failure_rejected(self):
        self.assertEqual(
            audit.evaluate_parent(st(), acl("not supported", 255), "paperless-sync")[0],
            "UNKNOWN_PARENT_ACL_STATE")

    def test_unparsable_acl_or_unexpected_principal_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "UNRECOGNIZED_NATIVE_ACL_ENTRY"):
            audit.parse_native_aces("group:everyone:allow:UNKNOWN\n")

    def test_device_boundary_finds_root_above_source(self):
        source = Path("/volume1/homes/thomas/Paperless")
        statuses = {
            source: st(dev=300),
            Path("/volume1/homes/thomas"): st(dev=300),
            Path("/volume1/homes"): st(dev=300),
            Path("/volume1"): st(dev=200),
        }
        with patch.object(audit, "checked_directory", side_effect=lambda p: statuses[p]):
            self.assertEqual(audit.device_boundary(source), Path("/volume1/homes"))

    def test_device_root_source_cannot_be_selected(self):
        source = Path("/volume1/homes")
        statuses = {source: st(dev=300), Path("/volume1"): st(dev=200)}
        with patch.object(audit, "checked_directory", side_effect=lambda p: statuses[p]):
            with self.assertRaisesRegex(RuntimeError, "SOURCE_IS_DEVICE_ROOT"):
                audit.device_boundary(source)

    def test_readonly_code_never_creates_or_removes(self):
        src = MODULE.read_text()
        for mutation in (".mkdir(", "os.mkdir(", "os.unlink(", ".unlink(",
                         "os.rename(", "os.replace(", "shutil.move(",
                         "chmod(", "chown(", "subprocess.Popen("):
            self.assertNotIn(mutation, src)


if __name__ == "__main__":
    unittest.main()
