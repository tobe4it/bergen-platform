"""Offline release wrapper tests. Root gate writes occur ONLY in temporary fixtures."""
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "ansible/files/paperless"
SPEC = importlib.util.spec_from_file_location(
    "group_exact_release", CODE / "synology_one_group_archive_release.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def proof(scope="Familie", name="Scan.pdf", sha="a"*64):
    return {
        "schema_version": 1,
        "sender_receipt": hashlib.sha256(
            (scope + "\0" + name).encode()).hexdigest() + ".json",
        "bridge_receipt": "b"*24 + ".json",
        "receiver_source": scope + "/" + name[:-4] + "--nas-" + sha + ".pdf",
        "sha256": sha,
        "document_id": 23,
    }


class GroupExactReleaseTests(unittest.TestCase):
    def test_one_exact_group_release_manifest_matches_worker_schema(self):
        p = proof()
        result = json.loads(m.manifest("Familie/Scan.pdf", p, 1000))
        self.assertEqual(result["scope"], "Familie")
        self.assertEqual(result["site"], "paperless-scan")
        self.assertEqual(result["source"], "Scan.pdf")
        self.assertEqual(result["sender_receipt"], p["sender_receipt"])
        self.assertEqual(result["issued_at"], 1000)
        self.assertEqual(result["expires_at"], 1600)
        self.assertEqual(result["release"], "one_original_pdf")

    def test_parent_and_private_scopes_cannot_be_committed(self):
        for only in ("Privat/thomas/Scan.pdf", "Privat/nadja/Scan.pdf",
                     "Familie/.Scan.pdf", "Familie/../Scan.pdf",
                     "Eltern/foo/bar.pdf", "Familie/Scan.txt",
                     "Familie/Scan.pdf/other.pdf", "Familie/",
                     "Familie/.", "Familie/.."):
            with self.subTest(only=only), self.assertRaises(RuntimeError):
                m.manifest(only, proof(), 100)

    def test_manifests_pin_all_import_proof_fields(self):
        original = proof()
        for field, value in (
            ("sender_receipt", "0"*64 + ".json"),
            ("bridge_receipt", "Z"*24 + ".json"),
            ("receiver_source", "Privat/thomas/Scan--nas-" + "a"*64 + ".pdf"),
            ("sha256", "not-sha"),
            ("document_id", True),
            ("schema_version", True),
        ):
            p = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                m.manifest("Familie/Scan.pdf", p, 12345)

    def test_no_purge_or_broad_site_activation_or_private_scopes(self):
        source = (CODE / "synology_one_group_archive_release.py").read_text()
        playbook = (ROOT / "ansible/playbooks/commit-paperless-one-group-v1-archive.yml").read_text()
        self.assertIn('GATE = "archive-move.paperless-scan.enabled"', source)
        self.assertNotIn("archive-move.paperless-scan.enabled", playbook)
        self.assertIn("ONE_GROUP_PDF_ARCHIVE_COMPLETED", playbook)
        self.assertIn("group_before_archive_count", playbook)
        self.assertIn("POST_MOVE_LIFECYCLE_RECONCILED", playbook)
        self.assertIn("paperless_archive_commit | default(false)) is sameas true", playbook)
        self.assertNotIn("shutil.rmtree", source)
        self.assertNotIn("os.rmdir(", source)
        self.assertNotIn("purge_archive(", source)

    def _run_temp(self, *, outcome="ok", preexisting=False):
        with tempfile.TemporaryDirectory(prefix="bp-group-release-", dir="/tmp") as tmp:
            parent = Path(tmp)
            (parent / "bin").mkdir()
            (parent / "bin/synology_same_volume_archive_move.py").write_text("# synthetic\n")
            p = proof()
            gate = parent / m.GATE
            if preexisting:
                gate.write_text("operator marker\n")
            settings = {"parent": parent, "sync_user": "paperless-sync",
                        "sources": [("dummy", x) for x in (
                            "Eltern", "Familie", "Privat/thomas", "Privat/nadja")]}
            captured = []
            def fake_call(argv, **kwargs):
                self.assertTrue(gate.exists())
                manifest = json.loads(gate.read_bytes())
                self.assertEqual(manifest["source"], "Scan.pdf")
                self.assertEqual(manifest["sender_receipt"], p["sender_receipt"])
                self.assertEqual(stat.S_IMODE(gate.stat().st_mode), 0o600)
                self.assertTrue(argv[-1] == "--commit")
                self.assertEqual(json.loads(kwargs["input"]), p)
                captured.append(argv)
                if outcome == "failure":
                    return SimpleNamespace(returncode=7, stdout="", stderr="fail")
                return SimpleNamespace(returncode=0,
                    stdout=("ARCHIVE_MOVED " + p["sender_receipt"] +
                            " 2026-10 " + p["sender_receipt"][:-5] +
                            ".pdf\nARCHIVE_PURGE_DISABLED\n"),
                    stderr="")
            # Do NOT touch production paths or real user identity.
            with patch.object(m.os, "geteuid", return_value=0), \
                 patch.object(m, "verify_dir"), \
                 patch.object(m, "safe_file"), \
                 patch.object(m.pwd, "getpwnam",
                     return_value=SimpleNamespace(pw_uid=1048, pw_gid=1048,
                                                  pw_name="paperless-sync")), \
                 patch.dict(sys.modules, {"synology_config": SimpleNamespace(SETTINGS=settings)}):
                if preexisting or outcome == "failure":
                    with self.assertRaises(RuntimeError):
                        m.execute(parent, "Familie/Scan.pdf", p,
                                  call=fake_call, now=1234)
                else:
                    m.execute(parent, "Familie/Scan.pdf", p,
                              call=fake_call, now=1234)
            self.assertEqual(gate.exists(), preexisting)
            self.assertEqual(len(captured), 0 if preexisting else 1)

    def test_success_stages_and_revokes_exact_gate(self):
        self._run_temp(outcome="ok")

    def test_failed_worker_still_revokes_gate(self):
        self._run_temp(outcome="failure")

    def test_preexisting_gate_refused_and_never_removed(self):
        self._run_temp(outcome="ok", preexisting=True)


if __name__ == "__main__":
    unittest.main()
