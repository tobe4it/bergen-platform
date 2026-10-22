"""Offline fail-closed regression for dedicated Bergen-AI vmbr90 transport apply."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/preflight_vmbr90_scoped_apply_readonly.py"
PLAY = ROOT / "ansible/playbooks/apply-bergen-ai-vmbr90-transport-once.yml"
spec = importlib.util.spec_from_file_location("vmbr90_preflight", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class Vmbr90ScopedApplyTests(TestCase):
    def test_guest_must_be_running_with_only_preexisting_eth0(self):
        original = (
            "hostname: bergen-ai\nunprivileged: 1\n"
            "net0: name=eth0,bridge=vmbr20,ip=dhcp\n")
        with mock.patch.object(a, "run", side_effect=[original, "status: running\n"]):
            self.assertEqual(a.guest(110, "bergen-ai"), "RUNNING_NET0_ONLY")
        for config in (
            original + "net1: name=eth1,bridge=vmbr90\n",
            original + "net1: name=eth1,bridge=vmbr1\n",
            original.replace("name=eth0", "name=eth2"),
            original.replace("bergen-ai", "not-bergen-ai"),
            original.replace("unprivileged: 1", "unprivileged: 0"),
        ):
            with self.subTest(config=config), mock.patch.object(
                    a, "run", side_effect=[config, "status: running\n"]):
                self.assertNotEqual(a.guest(110, "bergen-ai"), "RUNNING_NET0_ONLY")
        with mock.patch.object(a, "run", side_effect=[original, "status: stopped\n"]):
            self.assertEqual(a.guest(110, "bergen-ai"), "UNVERIFIED")

    def test_status_never_implicitly_authorizes_write(self):
        with (mock.patch.object(a, "host_config", return_value="EXPLICIT_SOURCE_NO_PENDING_EDIT"),
              mock.patch.object(a, "guest", return_value="RUNNING_NET0_ONLY")):
            result = a.report()
        self.assertEqual(result["STATUS"], "SCOPED_HOST_PREFLIGHT_PASSED")
        self.assertFalse(result["APPLY_AUTHORIZED"])
        self.assertFalse(result["CHANGED"])
        with (mock.patch.object(a, "host_config", return_value="PENDING_PVE_NETWORK_EDIT"),
              mock.patch.object(a, "guest", return_value="RUNNING_NET0_ONLY")):
            self.assertEqual(a.report()["STATUS"], "REVIEW_REQUIRED")

    def test_apply_requires_external_ipam_full_scope_and_real_console_attestation(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual([p["import_playbook"] for p in plays[:4]], [
            "audit-bergen-ai-private-bridge-external-gates-readonly.yml",
            "audit-bergen-ai-private-bridge-readonly.yml",
            "audit-bergen-ai-private-bridge-extended-readonly.yml",
            "audit-bergen-ai-private-bridge-wg-readonly.yml",
        ])
        p = plays[4]
        self.assertEqual(p["hosts"], "venombox")
        self.assertTrue(p["become"])
        self.assertEqual(p["serial"], 1)
        tasks = p["tasks"]
        self.assertEqual(p["vars"]["bergen_ai_vmbr90_oneoff_approval"], "")
        self.assertEqual(p["vars"]["bergen_ai_vmbr90_oob_attestation"], "")
        first = tasks[0]["ansible.builtin.assert"]["that"]
        self.assertIn("hostvars['localhost'].ipam_gate.SCOPE_COVERAGE == 'OPERATOR_DECLARED_COMPLETE'", first)
        self.assertIn("ai_bridge_wg.STATUS == 'NO_OVERLAP_IN_INSPECTED_LIVE_WG_PEERS'", first)
        self.assertIn("bergen_ai_vmbr90_oob_attestation == 'CONSOLE_VERIFIED_AND_ROLLBACK_AVAILABLE'", first)
        self.assertIn("rollback_gate.CT126_BACKUP == 'RECENT_FILE_METADATA_ONLY'", first)
        self.assertIn("bp_ai_bridge_audit.BRIDGE_CONFIG == 'ABSENT'", first)
        self.assertTrue(all(isinstance(x, str) for x in first))

    def test_apply_never_changes_primary_nic_default_gateway_or_services(self):
        source = PLAY.read_text()
        for forbidden in ("--net0", "ifreload -a", "pct stop", "pct restart",
                          "pct reboot", "systemctl restart", "vmbr0", "pct destroy",
                          "qm stop", "rm -rf", "curl", "wget", "OLLAMA_HOST="):
            self.assertNotIn(forbidden, source)
        self.assertIn("bridge-ports none", source)
        self.assertIn("post-up echo 1 > /proc/sys/net/ipv6/conf/vmbr90/disable_ipv6", source)
        self.assertIn("scoped_bridge_ipv6.stdout | trim == '1'", source)
        self.assertIn("scoped_bridge_ports.stdout | from_json | length == 0", source)
        self.assertIn("iface vmbr90 inet manual", source)
        self.assertIn("argv: [ifup, vmbr90]", source)
        self.assertIn("argv: [ifdown, vmbr90]", source)
        self.assertIn("172.30.110.2/28,ip6=manual,firewall=1", source)
        self.assertIn("172.30.110.3/28,ip6=manual,firewall=1", source)
        self.assertIn("scoped_interfaces_before.stat.checksum == scoped_interfaces_after.stat.checksum", source)
        self.assertIn("scoped_ct110_net0_before", source)
        self.assertIn("scoped_ct126_net0_before", source)
        self.assertIn("PAPERLESS_AI_ENDPOINT_CHANGED=NO", source)
        self.assertNotIn("delegate_to: localhost", source)

    def test_apply_rolls_back_only_own_exact_net1_and_file(self):
        p = yaml.safe_load(PLAY.read_text())[4]
        block_task = next(t for t in p["tasks"] if "block" in t)
        block = block_task["block"]
        rescue = block_task["rescue"]
        assert all(x.get("no_log", False) for x in block
                   if "ansible.builtin.command" in x and "pct, set" in str(x))
        assert any(t.get("ansible.builtin.command", {}).get("argv") ==
                   ["pct", "set", "110", "--delete", "net1"] for t in rescue)
        assert any(t.get("ansible.builtin.command", {}).get("argv") ==
                   ["pct", "set", "126", "--delete", "net1"] for t in rescue)
        assert any("bridge=vmbr90" in str(t) for t in rescue)
        self.assertTrue(any(t.get("ansible.builtin.file", {}).get("state") == "absent"
                            for t in rescue))
        self.assertIn("NO", str(block[-1]))  # No Ollama/Paperless changes.

    def test_preflight_python_does_not_run_writes(self):
        ast.parse(SCRIPT.read_text())
        for text in ("pct set", "pct stop", "pct restart", "ifup vmbr90",
                     "os.unlink", "write_text(", "rm -rf"):
            self.assertNotIn(text, SCRIPT.read_text())


if __name__ == "__main__":
    import unittest
    unittest.main()
