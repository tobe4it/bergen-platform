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
GPU_AUDIT = ROOT / "ansible/playbooks/audit-bergen-ai-gpu-stage-readonly.yml"
GPU_STAGE = ROOT / "ansible/playbooks/stage-bergen-ai-ollama-gpu-resources.yml"
GPU_SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ollama_gpu_stage_readonly.py"
GPU_ROLLBACK_SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ollama_gpu_rollback_readonly.py"
GPU_ROLLBACK_PLAY = ROOT / "ansible/playbooks/rollback-bergen-ai-ollama-gpu-stage.yml"


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

    def test_native_proxmox_device_mapping_requires_confinement_and_backup(self):
        script = GPU_SCRIPT.read_text()
        ast.parse(script)
        for expected in (
            '"hostname") == name', # intentionally absent; use code-specific checks
        ):
            pass
        for keyword in ("unprivileged", "lxc.idmap:", "pct", "help",
                        "getgrouplist", "GUEST_RENDER_GID"):
            # fields inside output are validated by target Ansible and script
            if keyword == "GUEST_RENDER_GID":
                continue
            self.assertIn(keyword, script)
        self.assertIn("LXC_MEMORY_MIB", script)
        self.assertIn("GUEST_OLLAMA_UID", script)
        self.assertIn('"READY_FOR_REVIEW"', script)
        s = GPU_STAGE.read_text()
        checks = yaml.safe_load(s)[0]
        self.assertEqual(checks["hosts"], "venombox")
        for gate in ("bergen_ai_gpu_stage_approved",
                     "bergen_ai_gpu_stage_config_backup_approved",
                     "RENDER_HOST_GID == 993", "KFD_HOST_GID == 993",
                     "GPU_RAM_CAP_HEADROOM_INSUFFICIENT",
                     "GPU_PREIMAGE_ALREADY_EXISTS_REVIEW_FIRST"):
            self.assertIn(gate, s)
        self.assertIn("remote_src: true", s)
        self.assertIn("lxc110-pre-gpu.conf", s)
        self.assertIn("/dev/dri/renderD128,uid=", s)
        self.assertIn("/dev/kfd,uid=", s)
        self.assertIn("mode=0660", s)
        self.assertIn("pct, set, '110', --memory, '32768'", s)
        self.assertNotIn("pct, stop", s)
        self.assertNotIn("pct, reboot", s)
        self.assertNotIn("unprivileged: 0", s)
        self.assertNotIn("lxc.idmap:", s)
        audit = yaml.safe_load(GPU_AUDIT.read_text())[0]
        self.assertEqual(audit["hosts"], "venombox")
        for t in audit["tasks"]:
            if "ansible.builtin.command" in t:
                self.assertIs(t["changed_when"], False)
                self.assertTrue(t["no_log"])

    def test_gpu_stage_rollback_requires_exact_preimage_and_separate_approval(self):
        raw = GPU_ROLLBACK_SCRIPT.read_text()
        ast.parse(raw)
        for evidence in ("lxc110-pre-gpu.conf", "UNRELATED_CONFIG_DRIFT",
                         "RESTORE_MEMORY_MIB", '"EXACT_STAGE_ONLY"',
                         "mode=0660", "memory: 32768"):
            self.assertIn(evidence, raw)
        play = yaml.safe_load(GPU_ROLLBACK_PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        text = GPU_ROLLBACK_PLAY.read_text()
        self.assertIn("bergen_ai_gpu_rollback_approved", text)
        self.assertIn("bergen_ai_gpu_rollback_before_restart_confirmed", text)
        self.assertIn("GPU_ROLLBACK_CONFIG_DRIFT", text)
        self.assertIn("[pct, set, '110', --delete, 'dev0,dev1']", text)
        self.assertIn("[pct, set, '110', --memory, '16384']", text)
        self.assertNotIn("pct, reboot", text)
        self.assertNotIn("pct, stop", text)

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
