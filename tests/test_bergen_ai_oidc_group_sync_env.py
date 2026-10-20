"""Offline fail-closed contracts for tokenless Open WebUI group mapping."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/manage-bergen-ai-oidc-group-sync-env.yml"
SOURCE = ROOT / "ansible/templates/open-webui/oidc.env.j2"
ORIGINAL = ROOT / "ansible/playbooks/configure-open-webui-oidc.yml"


class GroupSyncEnvTest(unittest.TestCase):
    def test_template_enables_only_existing_groups(self):
        source = SOURCE.read_text()
        expected = [
            "OAUTH_SCOPES=openid email groups",
            "OAUTH_GROUPS_CLAIM=groups",
            "ENABLE_OAUTH_GROUP_MANAGEMENT=true",
            "ENABLE_OAUTH_GROUP_CREATION=false",
            "ENABLE_OAUTH_ROLE_MANAGEMENT=false",
            "DEFAULT_USER_ROLE=pending",
            "ENABLE_OAUTH_PERSISTENT_CONFIG=false",
        ]
        for line in expected:
            self.assertIn(line, source)
        self.assertNotIn("ENABLE_OAUTH_ROLE_MANAGEMENT=true", source)
        self.assertNotIn("DEFAULT_USER_ROLE=admin", source)
        self.assertEqual(source.count("ENABLE_OAUTH_GROUP_MANAGEMENT="), 1)
        self.assertIn("{{ vault_open_webui_oidc_client_secret }}", source)

    def test_playbook_audit_default_and_controlled_apply(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "bergen-ai")
        self.assertTrue(play["become"])
        self.assertEqual(play["vars"]["bp_sync_mode"],
                         "{{ bergen_ai_oidc_env_group_mode | default('audit') }}")
        tasks = play["tasks"]
        gates = str(next(t["ansible.builtin.assert"] for t in tasks
                         if t["name"].startswith("Require exact target")))
        for requirement in (
            "bergen_ai_oidc_env_group_approved",
            "bergen_ai_oidc_env_backup_verified",
            "bergen_ai_oidc_env_expected_sha256",
            "bergen_ai_oidc_env_rollback_approved",
            "ansible_check_mode",
        ):
            self.assertIn(requirement, gates)
        self.assertIn("OIDC_GROUP_ENV_POLICY_DRIFT", PLAY.read_text())
        self.assertIn("OIDC_GROUP_ENV_FINGERPRINT_OR_STATE_CHANGED",
                      PLAY.read_text())
        self.assertIn("ROLLBACK_ENVIRONMENT_DRIFT_REQUIRES_REVIEW",
                      PLAY.read_text())
        self.assertIn("MISSING_OR_EMPTY_GROUP_CLAIM_REVOKE=NOT_PROVEN_ON_0_10_2",
                      PLAY.read_text())
        self.assertIn("OAUTH_PERSISTENT_CONFIG", PLAY.read_text())
        self.assertIn("RESTARTED_SERVICE=open-webui.service", PLAY.read_text())
        self.assertNotIn("vault_open_webui_admin_token", PLAY.read_text())
        self.assertNotIn("ansible.builtin.shell:", PLAY.read_text())
        self.assertNotIn("ansible.builtin.replace:", PLAY.read_text())
        for t in tasks:
            if ("ansible.builtin.slurp" in t
                    or "ansible.builtin.copy" in t
                    or "ansible.builtin.lineinfile" in t):
                self.assertTrue(t.get("no_log", False), t["name"])
        backups = [t for t in tasks if t["name"].startswith(
            "Preserve exact secret OIDC environment")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["ansible.builtin.copy"]["mode"], "0600")
        self.assertEqual(backups[0]["when"], "bp_sync_mode == 'apply'")
        self.assertTrue(backups[0].get("no_log"))
        edits = [t for t in tasks if t["name"].startswith(
            "Turn on only existing native")]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["ansible.builtin.lineinfile"]["backrefs"], True)
        self.assertEqual(edits[0]["when"], "bp_sync_mode == 'apply'")
        handler = play["handlers"][0]
        self.assertEqual(handler["ansible.builtin.systemd_service"]["name"],
                         "open-webui.service")

    def test_original_ansible_source_is_now_release_gated(self):
        play = yaml.safe_load(ORIGINAL.read_text())[0]
        text = str(play["tasks"])
        self.assertIn("open_webui_oidc_group_sync_approved", text)
        self.assertIn("open_webui_oidc_group_sync_backup_verified", text)
        self.assertIn("open_webui_oidc_group_sync_membership_reviewed", text)


if __name__ == "__main__":
    unittest.main()
