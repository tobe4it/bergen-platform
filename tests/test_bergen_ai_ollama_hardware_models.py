"""Offline safety tests for the venombox GPU and local Ollama model rollout."""
import ast
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "ansible/files/bergen_ai/audit_ollama_hardware_readonly.py"
PLAN = ROOT / "ansible/files/bergen_ai/plan_ollama_models_readonly.py"
AUDIT = ROOT / "ansible/playbooks/audit-bergen-ai-ollama-hardware-readonly.yml"
PULL = ROOT / "ansible/playbooks/manage-bergen-ai-ollama-models.yml"


class OllamaHardwareTests(unittest.TestCase):
    def test_scripts_parse_and_audit_does_not_mutate(self):
        for f in [HW, PLAN]:
            src = f.read_text()
            ast.parse(src, filename=str(f))
            for forbidden in [
                "pct set", "pct stop", "pct reboot", "pct start",
                "systemctl restart", "chown(", "chmod(", "mkdir(",
                "ollama pull", "rm -rf", "lxc.idmap:", "OLLAMA_HOST=0.0.0.0",
            ]:
                self.assertNotIn(forbidden, src)
        self.assertIn("BERGEN_AI_MODEL_PREFLIGHT_V1:", HW.read_text())
        self.assertIn("BERGEN_AI_MODEL_PLAN_V1:", PLAN.read_text())
        self.assertIn("stat.S_ISCHR", HW.read_text())
        self.assertIn("os.major", HW.read_text())
        self.assertIn("os.minor", HW.read_text())

    def test_no_insecure_gpu_mapping_or_host_network_opening(self):
        data = AUDIT.read_text() + PULL.read_text()
        self.assertNotIn("unprivileged: 0", data)
        self.assertNotIn("c 511:*", data)
        self.assertNotIn("lxc.mount.entry:", data)
        self.assertNotIn("lxc.idmap:", data)
        self.assertNotIn("0.0.0.0:11434", data)
        self.assertNotIn("OLLAMA_KEEP_ALIVE=24h", data)

    def test_preflight_has_single_pve_target_and_only_read_tasks(self):
        play = yaml.safe_load(AUDIT.read_text())
        self.assertEqual(len(play), 1)
        self.assertEqual(play[0]["hosts"], "venombox")
        tasks = play[0]["tasks"]
        commands = [t for t in tasks if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertIs(commands[0]["changed_when"], False)
        self.assertIn("UNPRIVILEGED", AUDIT.read_text())

    def test_installer_default_audit_and_never_deletes_models(self):
        p = yaml.safe_load(PULL.read_text())[0]
        self.assertEqual(p["hosts"], "venombox")
        self.assertIn("default('audit')", str(p["vars"]["bergen_ai_models_action"]))
        src = PULL.read_text()
        for x in ["bergen_ai_models_approved", "bergen_ai_models_download_window_approved",
                  "bergen_ai_models_large_approved", "OLLAMA_MODEL_CAPACITY_OR_APPROVAL_FAILED",
                  "UNREVIEWED_LXC", "READY_FOR_EXPLICIT_APPROVAL"]:
            self.assertIn(x, src)
        self.assertNotIn("ollama rm", src)
        self.assertNotIn("ollama serve", src)
        pulls = [t for t in p["tasks"] if "Pull only approved" in t["name"]]
        self.assertEqual(len(pulls), 1)
        self.assertIn("bergen_ai_models_action == 'apply'", str(pulls[0]["when"]))
        self.assertTrue(pulls[0]["no_log"])

    def test_32b_is_only_with_separate_review_and_headroom(self):
        src = PLAN.read_text()
        self.assertIn('"qwen2.5:32b-instruct-q4_K_M": 22', src)
        self.assertIn('"qwen2.5:14b-instruct-q4_K_M": 10', src)
        self.assertIn('"mistral-nemo:12b": 8', src)
        self.assertIn('"bge-m3": 2', src)
        self.assertIn("not request.get(\"large_model_review\")", src)
        self.assertIn("+15", src)
        self.assertIn('not isinstance(models,list)', src)


if __name__ == "__main__":
    unittest.main()
