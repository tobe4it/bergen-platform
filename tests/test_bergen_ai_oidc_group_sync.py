"""Synthetic API + SQLite regression tests for OIDC group sync v0.10.2."""
import importlib.util
import io
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "ansible/files/bergen_ai/manage_oidc_group_sync_v0102.py"
PLAY = ROOT / "ansible/playbooks/manage-bergen-ai-oidc-group-sync.yml"
spec = importlib.util.spec_from_file_location("oidc_group_apply", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NAMES = {
    "family": "Family@instance.invalid",
    "adults": "Parents@instance.invalid",
    "children": "Kids@instance.invalid",
}
IDS = {"family": "f", "adults": "a", "children": "c"}


class GroupSyncTest(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "webui.db"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            CREATE TABLE "model" (id TEXT PRIMARY KEY);
            CREATE TABLE "group_member" (group_id TEXT, user_id TEXT);
            CREATE TABLE access_grant (
              resource_type TEXT, resource_id TEXT,
              principal_type TEXT, principal_id TEXT, permission TEXT);
            """)
            for mid, role in mod.MODEL_IDS.items():
                db.execute('INSERT INTO "model" VALUES (?)', (mid,))
                db.execute("INSERT INTO access_grant VALUES (?,?,?,?,?)",
                           ("model", mid, "group", IDS[role], "read"))
        self.config = {
            "ENABLE_OAUTH_GROUP_MANAGEMENT": False,
            "ENABLE_OAUTH_GROUP_CREATION": False,
            "ENABLE_OAUTH_ROLE_MANAGEMENT": False,
            "OAUTH_GROUP_CLAIM": "",
            "OAUTH_SCOPES": "openid email groups",
            "OAUTH_CLIENT_SECRET": "dont-echo-my-secret",
        }
        self.admin = {"DEFAULT_USER_ROLE": "pending", "ENABLE_API_KEYS": True}
        self.calls = []

    def fake_api(self, method, path, token, data=None):
        self.calls.append((method, path, data))
        if path == "/api/version":
            return {"version": "0.10.2"}
        if path == "/api/v1/auths/admin/config/oauth":
            if method == "POST":
                self.config.update(data)
            return dict(self.config)
        if path == "/api/v1/auths/admin/config":
            return dict(self.admin)
        if path == "/api/v1/groups/":
            return [{"id": IDS[role], "name": NAMES[role]}
                    for role in NAMES]
        raise AssertionError(path)

    def run_case(self, mode="audit", **kwargs):
        data = {
            "protocol": "group-sync-v1",
            "mode": mode, "token": "x" * 40, "groups": NAMES,
            "approved": False, "backup_verified": False,
            "rollback_approved": False, "expected_sha256": "",
        }
        data.update(kwargs)
        output = io.StringIO()
        with patch.object(mod, "DATA", self.path), \
             patch.object(mod, "api", side_effect=self.fake_api), \
             patch.object(mod.sys, "stdin", io.StringIO(json.dumps(data))), \
             patch.object(mod.sys, "stdout", output):
            try:
                mod.run()
            except SystemExit as exc:
                self.assertEqual(exc.code, 2)
        return json.loads(output.getvalue().split(mod.FRAME)[-1])

    def test_audit_is_nonmutating_and_no_secrets_appear(self):
        report = self.run_case()
        self.assertEqual(report["AUDIT"], "READ_ONLY")
        self.assertEqual(report["STATUS"], "READY")
        self.assertTrue(report["PROFILES_PRIVATE_READY"])
        self.assertFalse(report["CHANGED"])
        self.assertEqual(report["EMPTY_OR_MISSING_CLAIM_REVOCATION"],
                         "NOT_SUPPORTED_BY_V0_10_2")
        self.assertNotIn("dont-echo", json.dumps(report))
        self.assertFalse(any(method == "POST" for method, _, _ in self.calls))

    def test_enable_only_group_mapping_with_gate_and_fingerprint(self):
        snapshot = self.run_case()["CONFIG_SHA256"]
        report = self.run_case(
            "apply", approved=True, backup_verified=True,
            expected_sha256=snapshot
        )
        self.assertEqual(report["STATUS"], "GROUP_SYNC_ENABLED")
        self.assertTrue(report["CHANGED"])
        posts = [call for call in self.calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1], "/api/v1/auths/admin/config/oauth")
        self.assertEqual(posts[0][2], {
            "ENABLE_OAUTH_GROUP_MANAGEMENT": True,
            "ENABLE_OAUTH_GROUP_CREATION": False,
            "ENABLE_OAUTH_ROLE_MANAGEMENT": False,
            "OAUTH_GROUP_CLAIM": "groups",
        })
        self.assertTrue(self.config["ENABLE_OAUTH_GROUP_MANAGEMENT"])
        self.assertEqual(self.config["OAUTH_CLIENT_SECRET"],
                         "dont-echo-my-secret")

    def test_apply_without_backup_fingerprint_or_consent_never_writes(self):
        snapshot = self.run_case()["CONFIG_SHA256"]
        for overrides in ({}, {"approved": True},
                          {"approved": True, "backup_verified": True},
                          {"approved": True, "backup_verified": True,
                           "expected_sha256": "0" * 64}):
            before = len([p for p in self.calls if p[0] == "POST"])
            result = self.run_case("apply", **overrides)
            self.assertEqual(result["AUDIT"], "FAILED_CLOSED")
            after = len([p for p in self.calls if p[0] == "POST"])
            self.assertEqual(before, after)

    def test_nonempty_members_reject_initial_enable(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO "group_member" VALUES (?,?)',
                       (IDS["children"], "known-child"))
        fingerprint = self.run_case()["CONFIG_SHA256"]
        outcome = self.run_case(
            "apply", approved=True, backup_verified=True,
            expected_sha256=fingerprint)
        self.assertEqual(outcome["STATUS"], "INITIAL_MEMBERSHIP_NOT_EMPTY")
        self.assertFalse(any(method == "POST" for method, _, _ in self.calls))

    def test_missing_private_model_or_wrong_grant_prevents_enable(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM access_grant WHERE resource_id=?",
                       ("bergen-kinder-lernen",))
        report = self.run_case()
        self.assertEqual(report["STATUS"], "PRIVATE_PROFILES_MISSING")
        outcome = self.run_case(
            "apply", approved=True, backup_verified=True,
            expected_sha256=report["CONFIG_SHA256"])
        self.assertEqual(outcome["STATUS"], "PRIVATE_PROFILES_MISSING")

    def test_bad_scopes_or_role_mapping_or_nonpending_role_rejects(self):
        for field, bad in [
            ("OAUTH_SCOPES", "openid email"),
            ("ENABLE_OAUTH_GROUP_CREATION", True),
            ("ENABLE_OAUTH_ROLE_MANAGEMENT", True),
            ("OAUTH_GROUP_CLAIM", "other.claim"),
        ]:
            with self.subTest(field=field):
                self.config[field] = bad
                report = self.run_case()
                self.assertEqual(report["AUDIT"], "FAILED_CLOSED")
                self.config[field] = ("openid email groups" if field == "OAUTH_SCOPES"
                                      else "" if field == "OAUTH_GROUP_CLAIM"
                                      else False)
        self.admin["DEFAULT_USER_ROLE"] = "user"
        report = self.run_case()
        self.assertEqual(report["STATUS"], "DEFAULT_ROLE_MUST_REMAIN_PENDING")

    def test_rollback_does_not_falsely_claim_membership_revoked(self):
        self.config["ENABLE_OAUTH_GROUP_MANAGEMENT"] = True
        self.config["OAUTH_GROUP_CLAIM"] = "groups"
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO "group_member" VALUES (?,?)',
                       (IDS["adults"], "some-adult"))
        current_sha = self.run_case()["CONFIG_SHA256"]
        result = self.run_case(
            "rollback", approved=True, backup_verified=True,
            rollback_approved=True, expected_sha256=current_sha
        )
        self.assertEqual(result["STATUS"],
                         "GROUP_SYNC_DISABLED_MEMBERSHIP_REVIEW_REQUIRED")
        self.assertEqual(result["REMAINING_GROUP_MEMBERS"], 1)
        self.assertFalse(self.config["ENABLE_OAUTH_GROUP_MANAGEMENT"])

    def test_playbook_has_no_secrets_or_unprotected_apply(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["serial"], 1)
        commands = [t for t in play["tasks"] if
                    "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertTrue(commands[0]["failed_when"] is False)
        assert_task = next(t for t in play["tasks"] if
                           "Enforce reviewed" in t["name"])
        gate = str(assert_task["ansible.builtin.assert"])
        self.assertIn("bergen_ai_group_sync_backup_verified", gate)
        self.assertIn("bergen_ai_group_sync_expected_sha256", gate)
        self.assertIn("vault_open_webui_admin_token", gate)
        self.assertTrue(assert_task["no_log"])
        self.assertIn("GROUP_SYNC_ENABLED", PLAY.read_text())
        src = FILE.read_text()
        self.assertIn("sqlite3.connect(", src)
        self.assertIn("PRAGMA query_only=ON", src)
        self.assertIn("POSTCHECK_FAILED", src)
        self.assertIn("SESSION_REVOCATION", src)
        self.assertNotIn("UPDATE group_member SET", src)
        self.assertNotIn("INSERT INTO group_member", src)
