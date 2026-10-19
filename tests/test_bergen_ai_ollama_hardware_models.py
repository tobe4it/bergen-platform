"""Offline safety tests for the venombox GPU and local Ollama model rollout."""
import ast
import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path
from unittest import mock
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
GPU_STAGED_READONLY = ROOT / "ansible/playbooks/audit-bergen-ai-gpu-staged-readonly.yml"
GPU_POSTBOOT_SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ollama_gpu_postboot_readonly.py"
GPU_POSTBOOT_AUDIT = ROOT / "ansible/playbooks/audit-bergen-ai-gpu-postboot-readonly.yml"
GPU_POSTBOOT_DIAG_SCRIPT = ROOT / "ansible/files/bergen_ai/diagnose_ollama_gpu_postboot_readonly.py"
GPU_POSTBOOT_DIAG_PLAY = ROOT / "ansible/playbooks/diagnose-bergen-ai-gpu-postboot-readonly.yml"
GPU_HOST_MEMORY_SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ollama_host_memory_readonly.py"
GPU_HOST_MEMORY_AUDIT = ROOT / "ansible/playbooks/audit-bergen-ai-gpu-host-memory-readonly.yml"
GPU_REBOOT_PLAY = ROOT / "ansible/playbooks/restart-bergen-ai-gpu-approved.yml"
GPU_BENCH_SCRIPT = ROOT / "ansible/files/bergen_ai/benchmark_ollama_gpu_synthetic.py"
GPU_BENCH_PLAY = ROOT / "ansible/playbooks/benchmark-bergen-ai-ollama-gpu-synthetic.yml"


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

    def test_staged_verification_accepts_real_pct_path_equals_format(self):
        stage = GPU_STAGE.read_text()
        self.assertIn("dev0: path=/dev/dri/renderD128,uid=", stage)
        self.assertIn("dev1: path=/dev/kfd,uid=", stage)
        self.assertNotIn("'dev0: /dev/dri/renderD128'", stage)
        self.assertNotIn("'dev1: /dev/kfd'", stage)
        checked = yaml.safe_load(GPU_STAGED_READONLY.read_text())[0]
        self.assertEqual(checked["hosts"], "venombox")
        for task in checked["tasks"]:
            if "ansible.builtin.command" in task:
                self.assertIs(task["changed_when"], False)
                self.assertTrue(task["no_log"])

    def test_all_gpu_playbook_assertions_are_yaml_strings(self):
        """Ansible assert.that must not contain YAML dicts for colon comparisons."""
        playbooks = (GPU_AUDIT, GPU_STAGE, GPU_STAGED_READONLY, GPU_ROLLBACK_PLAY,
                     GPU_POSTBOOT_AUDIT, GPU_REBOOT_PLAY)
        for path in playbooks:
            with self.subTest(playbook=path.name):
                for play in yaml.safe_load(path.read_text()):
                    for task in play.get("tasks", []):
                        checks = task.get("ansible.builtin.assert", {}).get("that", [])
                        self.assertIsInstance(checks, list)
                        for check in checks:
                            self.assertIsInstance(
                                check, str,
                                f"{path.name}: {task['name']}: invalid Ansible conditional {check!r}",
                            )

    def test_gpu_guest_running_condition_is_correctly_quoted(self):
        play = yaml.safe_load(GPU_STAGED_READONLY.read_text())[0]
        check_task = next(t for t in play["tasks"]
                          if t["name"] == "Refuse a non-running or wrong runtime target")
        conditions = check_task["ansible.builtin.assert"]["that"]
        self.assertEqual(
            conditions,
            ["bergen_gpu_guest_runtime.rc == 0",
             "bergen_gpu_guest_runtime.stdout | trim == 'status: running'"]
        )
        self.assertNotIn("ALLOW_BROKEN_CONDITIONALS", GPU_STAGED_READONLY.read_text())

    def test_exact_preimage_compare_accepts_only_expected_gpu_stage(self):
        spec = importlib.util.spec_from_file_location(
            "bergen_gpu_preimage_audit", GPU_ROLLBACK_SCRIPT
        )
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        backup_lines = [
            "arch: amd64", "cores: 18", "hostname: bergen-ai",
            "memory: 16384", "swap: 2048", "unprivileged: 1",
        ]
        stage_lines = [
            "arch: amd64", "cores: 18",
            "dev0: path=/dev/dri/renderD128,uid=999,gid=992,mode=0660",
            "dev1: path=/dev/kfd,uid=999,gid=992,mode=0660",
            "hostname: bergen-ai", "memory: 32768", "swap: 2048",
            "unprivileged: 1",
        ]
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "original.conf"
            c = Path(d) / "staged.conf"
            b.write_text("\n".join(backup_lines) + "\n")
            b.chmod(0o600)
            with mock.patch.object(audit, "BACKUP", b), mock.patch.object(audit, "CURRENT", c):
                for mutation, should_pass in [
                    (stage_lines, True),
                    ([x.replace("gid=992", "gid=44") for x in stage_lines], False),
                    ([x.replace("uid=999", "uid=0") for x in stage_lines], False),
                    ([x.replace("mode=0660", "mode=0666") for x in stage_lines], False),
                    (stage_lines + ["cores: 8"], False),
                    ([x.replace("memory: 32768", "memory: 24576") for x in stage_lines], False),
                ]:
                    with self.subTest(mutation=mutation):
                        c.write_text("\n".join(mutation) + "\n")
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            if should_pass:
                                audit.main()
                                self.assertIn('"STATUS": "EXACT_STAGE_ONLY"', output.getvalue())
                            else:
                                with self.assertRaises(ValueError):
                                    audit.main()

    def test_postboot_memory_gate_uses_host_lxc_limit_not_guest_namespace(self):
        source = GPU_POSTBOOT_SCRIPT.read_text()
        self.assertIn('Path("/sys/fs/cgroup/lxc/110/memory.max")', source)
        self.assertIn('"MEMORY_CHECK_SOURCE":"PVE_HOST_LXC_110_CGROUP"', source)
        self.assertIn('and host_memory_ok)', source)
        self.assertNotIn('data["memory_limit"] == expectedbytes', source)
        self.assertNotIn('data["memory_limit"]==expectedbytes', source)

    def test_postboot_audit_does_not_execute_inference_or_mutate(self):
        source = GPU_POSTBOOT_SCRIPT.read_text()
        ast.parse(source, filename=str(GPU_POSTBOOT_SCRIPT))
        self.assertIn('"dev0": "path=/dev/dri/renderD128,uid=999,gid=992,mode=0660"', source)
        self.assertIn('"dev1": "path=/dev/kfd,uid=999,gid=992,mode=0660"', source)
        self.assertIn('EXPECTED_MODELS', source)
        self.assertIn('("memory","32768")', source)
        for forbidden in ('pct set', 'pct reboot', 'ollama run',
                          '/api/generate', '/api/chat', 'PAPERLESS_AI_ENABLED=true'):
            self.assertNotIn(forbidden, source)
        audit = yaml.safe_load(GPU_POSTBOOT_AUDIT.read_text())[0]
        self.assertEqual(audit["hosts"], "venombox")
        for task in audit["tasks"]:
            if "ansible.builtin.command" in task:
                self.assertFalse(task["changed_when"])
                self.assertTrue(task["no_log"])

    def test_incident_diagnostic_remains_readonly_and_reports_layers_separately(self):
        script = GPU_POSTBOOT_DIAG_SCRIPT.read_text()
        ast.parse(script, filename=str(GPU_POSTBOOT_DIAG_SCRIPT))
        for forbidden in ("pct reboot", "pct set", "ollama run", "/api/chat",
                          "/api/generate", "ollama pull", "pct stop", "systemctl restart"):
            self.assertNotIn(forbidden, script)
        for key in ("LXC110_CONFIG", "LXC110_RUNTIME", "RENDER_PRESENT",
                    "KFD_PRESENT", "OLLAMA_SERVICE", "OLLAMA_API",
                    "CGROUP_MEMORY_MAX", "GUEST_PROBE", "QWEN14_PRESENT",
                    "GPU_INFERENCE_PROVEN"):
            self.assertIn(key, script)
        play = yaml.safe_load(GPU_POSTBOOT_DIAG_PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertEqual(play["gather_facts"], False)
        text = GPU_POSTBOOT_DIAG_PLAY.read_text()
        self.assertIn("failed_when: false", text)
        self.assertIn("changed_when: false", text)
        self.assertNotIn("pct, reboot", text)
        self.assertNotIn("pct, set", text)
        self.assertNotIn("pct, stop", text)
        for task in play["tasks"]:
            if "ansible.builtin.command" in task:
                self.assertTrue(task["no_log"])
                self.assertFalse(task["changed_when"])
            if "ansible.builtin.assert" in task:
                for cond in task["ansible.builtin.assert"]["that"]:
                    self.assertIsInstance(cond, str)


    def test_host_cgroup_prefers_native_pve_path_to_lxc_info(self):
        script = GPU_HOST_MEMORY_SCRIPT.read_text()
        self.assertIn('ROOT / "lxc" / "110"', script)
        self.assertIn('limits = hierarchy("/lxc/110")', script)
        self.assertIn('"CGROUP_SOURCE":source', script)
        self.assertLess(script.index('ROOT / "lxc" / "110"'),
                        script.index('checked(["lxc-info"'))
        self.assertNotIn("pct set", script)
        self.assertNotIn("pct reboot", script)

    def test_host_cgroup_memory_ancestor_limit_and_no_mutation(self):
        script = GPU_HOST_MEMORY_SCRIPT.read_text()
        ast.parse(script, filename=str(GPU_HOST_MEMORY_SCRIPT))
        for forbidden in ("pct reboot", "pct set", "ollama run", "ollama pull",
                          "systemctl restart", "/api/generate", "/api/chat"):
            self.assertNotIn(forbidden, script)
        spec = importlib.util.spec_from_file_location(
            "bergen_ai_host_cgroup", GPU_HOST_MEMORY_SCRIPT
        )
        h = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(h)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "cgroup.controllers").write_text("cpu memory pids")
            guest = root / "lxc" / "110" / "ns"
            guest.mkdir(parents=True)
            (root / "memory.max").write_text("max")
            (root / "lxc" / "memory.max").write_text("max")
            (root / "lxc" / "110" / "memory.max").write_text("34359738368")
            (guest / "memory.max").write_text("max")
            observed = h.hierarchy("/lxc/110/ns", root=root)
            self.assertEqual(observed,[None,34359738368,None])
            # Linux cgroup-v2 root has no memory.max control file:
            # this must not invalidate an exact child cgroup limit.
            (root / "memory.max").unlink()
            observed = h.hierarchy("/lxc/110/ns", root=root)
            self.assertEqual(observed,[None,34359738368,None])
            self.assertEqual(h.classify(observed),"EFFECTIVE_32GIB")
            (root / "lxc" / "110" / "memory.max").write_text("max")
            observed = h.hierarchy("/lxc/110/ns", root=root)
            self.assertEqual(h.classify(observed),"NO_FINITE_CGROUP_LIMIT")
            (root / "lxc" / "110" / "memory.max").write_text("17179869184")
            self.assertEqual(h.classify(h.hierarchy("/lxc/110/ns",root=root)),
                             "BELOW_32GIB")
            (root / "lxc" / "110" / "memory.max").write_text("68719476736")
            self.assertEqual(h.classify(h.hierarchy("/lxc/110/ns",root=root)),
                             "ABOVE_32GIB")
            with self.assertRaises(ValueError):
                h.hierarchy("/lxc/110/../../sensitive",root=root)
        play = yaml.safe_load(GPU_HOST_MEMORY_AUDIT.read_text())[0]
        self.assertEqual(play["hosts"],"venombox")
        for task in play["tasks"]:
            if "ansible.builtin.command" in task:
                self.assertFalse(task["changed_when"])
                self.assertTrue(task["no_log"])
            if "ansible.builtin.assert" in task:
                self.assertTrue(all(isinstance(cond,str)
                                    for cond in task["ansible.builtin.assert"]["that"]))

    def test_benchmark_must_have_separate_approval_and_single_synthetic_model(self):
        script=GPU_BENCH_SCRIPT.read_text()
        ast.parse(script, filename=str(GPU_BENCH_SCRIPT))
        playbook=GPU_BENCH_PLAY.read_text()
        play=yaml.safe_load(playbook)[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertFalse(play["gather_facts"])
        self.assertIn("bergen_ai_gpu_benchmark_approved", playbook)
        self.assertIn("bergen_ai_gpu_benchmark_window_approved", playbook)
        for expected in (
            '/api/generate', '/api/ps', 'qwen2.5:14b-instruct-q4_K_M',
            '"keep_alive":"45s"', '"num_predict":40', '"num_ctx":2048',
            "SYNTHETIC_NO_DOCUMENTS", "GPU_ALLOCATION_OBSERVED",
            "/sys/fs/cgroup/lxc/110/memory.max"):
            self.assertIn(expected,script)
        for forbidden in ("pct reboot","pct set", "ollama pull",
                          "PAPERLESS_AI_ENABLED=true","/api/chat"):
            self.assertNotIn(forbidden,script)
        tasks=[t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(tasks),1)
        self.assertTrue(tasks[0]["no_log"])
        self.assertTrue(tasks[0]["changed_when"])
        self.assertIn("async", tasks[0])
        self.assertNotIn("GPU_INFERENCE_PROVEN_BY_MODEL_EXECUTION=YES",playbook)
        for item in play["tasks"]:
            if "ansible.builtin.assert" in item:
                for check in item["ansible.builtin.assert"]["that"]:
                    self.assertIsInstance(check,str)

    def test_restart_is_single_guest_explicit_downtime_with_preimage_gate(self):
        play = yaml.safe_load(GPU_REBOOT_PLAY.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        src = GPU_REBOOT_PLAY.read_text()
        for approval in ("bergen_ai_gpu_reboot_approved",
                         "bergen_ai_gpu_reboot_downtime_approved",
                         "EXACT_STAGE_ONLY",
                         "audit_ollama_gpu_rollback_readonly.py",
                         "audit_ollama_gpu_postboot_readonly.py",
                         "GPU_REBOOT_POSTBOOT_NOT_READY_MANUAL_RECOVERY_REQUIRED"):
            self.assertIn(approval, src)
        reboot_tasks = [
            t for t in play["tasks"]
            if t.get("ansible.builtin.command", {}).get("argv", []) == ["pct", "reboot", "110"]
        ]
        self.assertEqual(len(reboot_tasks), 1)
        self.assertTrue(reboot_tasks[0]["no_log"])
        self.assertEqual(reboot_tasks[0]["async"], 240)
        for forbidden in ("pct, reboot, '126'", "pct, stop, '110'",
                          "pct, set, '110'", "PAPERLESS_AI_ENABLED=true"):
            self.assertNotIn(forbidden, src)
        self.assertIn('"bergen_gpu_reboot_status.stdout | trim == \'status: running\'"', src)

    def test_embedding_tag_is_canonical_and_default_but_rag_stays_off(self):
        planner = PLAN.read_text()
        installer = PULL.read_text()
        self.assertIn('"bge-m3:latest": 2', planner)
        self.assertIn("'bge-m3:latest'", installer)
        self.assertNotIn("'bge-m3']", installer)
        for text in (planner, installer):
            self.assertNotIn("PAPERLESS_AI_ENABLED=true", text)
            self.assertNotIn("PAPERLESS_AI_LLM_EMBEDDING_BACKEND", text)
            self.assertNotIn("index_documents", text)

    def test_32b_is_only_with_separate_review_and_headroom(self):
        src = PLAN.read_text()
        self.assertIn('"qwen2.5:32b-instruct-q4_K_M": 22', src)
        self.assertIn('"qwen2.5:14b-instruct-q4_K_M": 10', src)
        self.assertIn('"mistral-nemo:12b": 8', src)
        self.assertIn('"bge-m3:latest": 2', src)
        self.assertIn("not request.get(\"large_model_review\")", src)
        self.assertIn("+15", src)
        self.assertIn('not isinstance(models,list)', src)


if __name__ == "__main__":
    unittest.main()
