"""Offline regression gates for approved Open WebUI private model staging."""
import importlib.util
import io
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/manage_family_chat_profiles_v0102.py"
PLAY = ROOT / "ansible/playbooks/manage-bergen-ai-family-chat-profiles.yml"
PROMPT = ROOT / "ansible/files/bergen_ai/prompts/learning_companion_de_v1.md"
SPEC = importlib.util.spec_from_file_location("model_activate", SCRIPT)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)
GROUPS = {"family": "family@example.invalid",
          "adults": "parents@example.invalid",
          "children": "kids@example.invalid"}
GROUP_IDS = {"family": "f", "adults": "a", "children": "c"}
CHILD = PROMPT.read_text()
PLANS = api.profile_plan(GROUP_IDS, CHILD)


class StageContract(TestCase):
    def test_all_four_profiles_have_exact_scoped_read_grants(self):
        self.assertEqual(len(PLANS), 4)
        self.assertEqual(len({p["id"] for p in PLANS}), 4)
        self.assertEqual({p["base_model_id"] for p in PLANS},
                         {api.MODEL_A, api.MODEL_B})
        for item in PLANS:
            body = api.as_payload(item, GROUP_IDS)
            self.assertEqual(body["access_grants"], [{
                "principal_type": "group",
                "principal_id": GROUP_IDS[item["role"]],
                "permission": "read"
            }])
            self.assertEqual(body["base_model_id"], item["base_model_id"])
            self.assertNotEqual(body["id"], body["base_model_id"])
            self.assertTrue(body["is_active"])
            self.assertEqual(body["params"]["system"], item["prompt"])
        self.assertEqual(sum(p["role"] == "children" for p in PLANS), 2)
        self.assertEqual(sum(p["role"] == "adults" for p in PLANS), 2)
        self.assertTrue(all(p["prompt"] == CHILD for p in PLANS
                            if p["role"] == "children"))
        self.assertIn("Vorsagen untersagt", CHILD)
        self.assertIn("vollständige Übersetzung", CHILD)

    def test_public_or_cross_role_or_extra_grant_rejected(self):
        p = PLANS[1]
        obj = api.as_payload(p, GROUP_IDS)
        obj["user_id"] = "operator"
        self.assertTrue(api.matches_existing(obj, p, GROUP_IDS))
        for wrong in (
            [{"principal_type": "user", "principal_id": "*", "permission": "read"}],
            [{"principal_type": "group", "principal_id": GROUP_IDS["adults"], "permission": "read"}],
            [{"principal_type": "group", "principal_id": GROUP_IDS["children"], "permission": "write"}],
            [{"principal_type": "group", "principal_id": GROUP_IDS["children"], "permission": "read"},
             {"principal_type": "user", "principal_id": "*", "permission": "read"}],
            [], None,
        ):
            with self.subTest(wrong=wrong):
                altered = dict(obj, access_grants=wrong)
                self.assertFalse(api.matches_existing(altered, p, GROUP_IDS))
        altered = dict(obj, params={"system": "Vorsagen erlaubt"})
        self.assertFalse(api.matches_existing(altered, p, GROUP_IDS))

    def payload(self, mode="audit", **overrides):
        val = {"mode": mode, "token": "x" * 40,
               "expected_groups": GROUPS,
               "child_prompt": CHILD,
               "approved": False, "backup_verified": False,
               "rollback_approved": False, "expected_sha256": ""}
        val.update(overrides)
        return val

    def execute(self, req, initial="EMPTY_READY", final=None):
        def stage(*_):
            return initial, "a" * 64, PLANS, GROUP_IDS

        def stage_final(*_):
            return final, "b" * 64, PLANS, GROUP_IDS

        result = []
        def fake_call(method, path, body, token):
            result.append((method, path, body))
            return {"id": body["id"]} if path.endswith("/create") else True

        side_effect = [stage(), stage_final()] if final else [stage()]
        output = io.StringIO()
        with patch.object(api, "fetch_state", side_effect=side_effect), \
             patch.object(api, "call_json", side_effect=fake_call), \
             patch.object(api.sys, "stdin", io.StringIO(json.dumps(req))), \
             patch.object(api.sys, "stdout", output):
            try:
                api.run()
            except SystemExit as exc:
                self.assertEqual(exc.code, 2)
        return output.getvalue(), result

    def test_read_only_no_admin_writes(self):
        result, writes = self.execute(self.payload())
        self.assertIn('"AUDIT": "READ_ONLY"', result)
        self.assertIn('"CHANGED": false', result)
        self.assertEqual(writes, [])

    def test_apply_requires_snapshot_backup_approval(self):
        for overrides in (
            {},
            {"approved": True},
            {"approved": True, "backup_verified": True},
            {"approved": True, "backup_verified": True,
             "expected_sha256": "z" * 64}
        ):
            out, writes = self.execute(self.payload("apply", **overrides))
            self.assertIn("FAILED_CLOSED", out)
            self.assertEqual(writes, [])

    def test_approved_stage_only_four_private_profiles(self):
        out, writes = self.execute(self.payload(
            "apply", approved=True, backup_verified=True,
            expected_sha256="a" * 64), final="ALREADY_STAGED")
        self.assertIn("PRIVATE_PROFILES_STAGED", out)
        self.assertEqual(len(writes), 4)
        self.assertTrue(all(method == "POST" for method, path, _ in writes))
        self.assertTrue(all(path == "/api/v1/models/create" for _, path, _ in writes))
        self.assertEqual(
            [a["access_grants"][0]["principal_id"] for _, _, a in writes],
            ["a", "c", "a", "c"]
        )

    def test_never_mutate_existing_unreviewed_profiles(self):
        result, writes = self.execute(self.payload(
            "apply", approved=True, backup_verified=True,
            expected_sha256="a" * 64), initial="PROFILE_DRIFT")
        self.assertIn("PROFILE_DRIFT", result)
        self.assertEqual(writes, [])

    def test_rollback_requires_own_approval(self):
        result, writes = self.execute(self.payload(
            "rollback", approved=True, backup_verified=True,
            expected_sha256="a" * 64), initial="ALREADY_STAGED")
        self.assertIn("ROLLBACK_NOT_APPROVED", result)
        self.assertEqual(writes, [])

    def test_playbook_gates_and_no_secret_output(self):
        play = yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(play["serial"], 1)
        diagnostics = next(t for t in play["tasks"]
                           if t.get("name") == "Report non-secret prerequisites before protected gate")
        safe_debug = str(diagnostics["ansible.builtin.debug"])
        self.assertIn("ADMIN_BEARER_SOURCE", safe_debug)
        self.assertIn("ADMIN_BEARER_PRESENT", safe_debug)
        self.assertIn("GLOBAL_API_KEY_SWITCH_REQUIRED=NO", safe_debug)
        self.assertIn("THREE_GROUP_NAMES", safe_debug)
        self.assertNotIn("Bearer ", safe_debug)
        gates_task = next(t for t in play["tasks"]
                          if "Require approved target and independent per-model release gates" in t.get("name", ""))
        gates = str(gates_task["ansible.builtin.assert"])
        for name in ("bergen_ai_family_model_approved",
                     "bergen_ai_family_model_backup_verified",
                     "bergen_ai_family_model_expected_sha256",
                     "bergen_ai_family_model_rollback_approved",
                     "bp_family_model_admin_bearer"):
            self.assertIn(name, gates)
        cmd = next(t for t in play["tasks"]
                   if "Run version-locked WebUI API audit" in t.get("name", ""))
        self.assertTrue(cmd.get("no_log"))
        self.assertIn("manage_family_chat_profiles_v0102.py",
                      str(cmd["ansible.builtin.command"]))
        self.assertTrue(cmd["ansible.builtin.command"]["stdin"])
        src = SCRIPT.read_text()
        self.assertIn('uri=True', src)
        self.assertIn("PRAGMA query_only=ON", src)
        self.assertIn("GROUP_MEMBERSHIP_REVIEW_REQUIRED", src)
        self.assertIn("EFFECTIVE_OIDC_CONFIG_DRIFT", src)
        self.assertIn("MODEL_DB_API_MISMATCH", src)
        self.assertIn('return all_model_ids', src)
        self.assertIn("BYPASS_MODEL_ACCESS_CONTROL", src)
        self.assertIn('OIDC_GROUP_MANAGEMENT_UNREVIEWED', src)
        self.assertIn("ProxyHandler({})", src)
        self.assertIn("NoRedirect()", src)
        self.assertNotIn("sqlite3.connect(path)", src)
        self.assertNotIn("http://0.0.0.0", src)
        self.assertNotIn("INSERT INTO ", src)
        self.assertNotIn("UPDATE model SET ", src)
        self.assertNotIn("GROUPS_OR_PERMISSIONS_CHANGED=True", src)
