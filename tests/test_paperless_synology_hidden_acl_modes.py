"""Fail-closed tests for Synology Linux-mode hidden-archive ACL classification."""
import importlib.util
import stat
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

FILE = (Path(__file__).resolve().parents[1] /
        "ansible/files/paperless/audit_synology_scan_acls.py")
spec = importlib.util.spec_from_file_location("audit_synology_scan_acls", FILE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

SERVICE_UID = 1025
DEVICE = 1048641


def info(mode=0o700, owner=SERVICE_UID, device=DEVICE, kind=stat.S_IFDIR):
    return SimpleNamespace(st_mode=kind | mode, st_uid=owner, st_dev=device)


def result(rc=255, stdout="(synoacltool.c, 596)It's Linux mode\n", stderr=""):
    return subprocess.CompletedProcess(["synoacltool", "-get"], rc,
                                       stdout=stdout, stderr=stderr)


def state(reply=None, details=None):
    return audit.classify_hidden_acl(reply or result(),
                                     details or info(), SERVICE_UID, DEVICE)


class HiddenArchiveLinuxModeTests(unittest.TestCase):
    def test_real_synology_linux_mode_accepted_only_private(self):
        self.assertEqual(state(), "POSIX_PRIVATE")

    def test_linux_mode_message_can_be_on_stderr(self):
        self.assertEqual(state(result(255, "", "(synoacltool.c, 350)It's Linux mode\n")),
                         "POSIX_PRIVATE")

    def test_any_other_error_255_is_rejected(self):
        for msg in ("Permission denied", "not found", "",
                    "(synoacltool.c, 596)It's Linux mode\nPermission denied"):
            with self.subTest(message=msg):
                self.assertEqual(state(result(255, msg)), "ACL_QUERY_FAILED")

    def test_same_text_with_wrong_exit_status_is_rejected(self):
        for rc in (1, 2, 127):
            with self.subTest(rc=rc):
                self.assertEqual(state(result(rc)), "ACL_QUERY_FAILED")

    def test_native_synology_acl_requires_separate_review(self):
        native = "ACL version: 1\n[0] group:Familie@bergen.intern:allow:rwxpdDaARWc--:fd--\n"
        self.assertEqual(
            state(result(0, native)), "NATIVE_DSM_ACL_NEEDS_EXPLICIT_REVIEW")

    def test_wrong_owner_is_rejected(self):
        self.assertEqual(
            state(details=info(owner=0)), "UNSAFE_OWNER_MODE_TYPE_OR_DEVICE")

    def test_group_and_other_permissions_are_rejected(self):
        for mode in (0o755, 0o750, 0o770, 0o775, 0o777, 0o600, 0o000):
            with self.subTest(mode=oct(mode)):
                self.assertEqual(state(details=info(mode=mode)),
                                 "UNSAFE_OWNER_MODE_TYPE_OR_DEVICE")

    def test_different_device_is_rejected(self):
        self.assertEqual(
            state(details=info(device=DEVICE+1)),
            "UNSAFE_OWNER_MODE_TYPE_OR_DEVICE")

    def test_symlink_and_regular_file_are_rejected(self):
        for kind in (stat.S_IFLNK, stat.S_IFREG):
            with self.subTest(kind=kind):
                self.assertEqual(
                    state(details=info(kind=kind)),
                    "UNSAFE_OWNER_MODE_TYPE_OR_DEVICE")

    def test_unexpected_success_without_native_acl_still_needs_review(self):
        self.assertEqual(
            state(result(0, "(synoacltool.c, 596)It's Linux mode\n")),
            "NATIVE_DSM_ACL_NEEDS_EXPLICIT_REVIEW")


if __name__ == "__main__":
    unittest.main()
