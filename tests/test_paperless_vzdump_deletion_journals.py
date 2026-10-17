"""Offline regression tests for the pinned read-only backup journal audit."""
import importlib.util
import io
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/paperless/verify_vzdump_deletion_journals.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-deletion-journal-backup-integrity.yml"
BUNDLE = ROOT / "ansible/playbooks/audit-paperless-archive-preflight.yml"
spec = importlib.util.spec_from_file_location("vzdump_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class VzdumpContentAuditTests(unittest.TestCase):
    def test_expected_guest(self):
        audit.parse_guest_config(
            "hostname: bergen-paperless\nunprivileged: 1\n"
            "rootfs: local-zfs:subvol-126-disk-0,size=32G\n"
            "mp0: local-zfs:subvol-126-disk-1,mp=/srv/bergen-paperless,backup=1,size=100G\n"
        )

    def test_reject_unbacked_mp0(self):
        text = ("hostname: bergen-paperless\nunprivileged: 1\n"
                "rootfs: local-zfs:subvol-126-disk-0,size=32G\n")
        for mp in ("mp0: local-zfs:subvol-126-disk-1,mp=/srv/bergen-paperless,size=100G\n",
                   "mp0: local-zfs:subvol-126-disk-1,mp=/srv/bergen-paperless,backup=0\n"):
            with self.subTest(mp=mp):
                with self.assertRaisesRegex(RuntimeError, "MP0_BACKUP_INVALID"):
                    audit.parse_guest_config(text + mp)

    def test_reject_privileged_guest(self):
        with self.assertRaisesRegex(RuntimeError, "UNPRIVILEGED_REQUIRED"):
            audit.parse_guest_config("hostname: bergen-paperless\nunprivileged: 0\n")

    def test_digest(self):
        self.assertEqual(audit.digest_stream(io.BytesIO(b"abc")),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_pinned_hashes(self):
        self.assertEqual(set(audit.JOURNALS), {15, 26})
        self.assertEqual(audit.JOURNALS[15][1],
                         "7529da0e6f0b6dd33ee868e12f282a0c7d4b6392883d13992d81902b9dbdd34b")
        self.assertEqual(audit.JOURNALS[26][1],
                         "5e0030686637d7feb85d7a8607ada78d22c224e31d77f053ba14f4dc6ace7d0a")

    def test_no_mutation_and_release_block(self):
        s = SCRIPT.read_text(encoding="utf-8")
        p = PLAY.read_text(encoding="utf-8")
        b = BUNDLE.read_text(encoding="utf-8")
        for token in ("os.unlink(", "os.remove(", "os.rename(", "os.replace(", ".mkdir(",
                      ".unlink(", ".rename(", "shutil.move(", "os.chmod(", "os.chown("):
            self.assertNotIn(token, s)
        self.assertIn('"tar", "--zstd", "-xOf"', s)
        self.assertIn("changed_when: false", p)
        self.assertIn("audit-paperless-synology-acls.yml", b)
        self.assertIn("SOURCE_DELETE_NOT_AUTHORIZED", b)
        self.assertIn("MAIN_MERGE_NOT_AUTHORIZED", s + b)


if __name__ == "__main__":
    unittest.main()
