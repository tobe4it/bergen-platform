"""Offline fail-closed tests: proposed private Bergen-AI PVE bridge, no live writes."""
import ast
import importlib.util
import ipaddress
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_private_bridge_preflight.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-private-bridge-readonly.yml"

spec = importlib.util.spec_from_file_location("bergen_ai_private_bridge_preflight", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class PrivateBridgeAuditTest(TestCase):
    def test_script_parses_and_exposes_only_sanitized_no_write_inventory(self):
        src = SCRIPT.read_text()
        ast.parse(src)
        self.assertEqual(bridge.BRIDGE, "vmbr90")
        self.assertEqual(str(bridge.CANDIDATE), "172.30.110.0/28")
        for identifier in (
            "pct", "ip", "network_overlaps", "single_ct_identity",
            "any_guest_references_bridge", "SUBNET_CLEARANCE",
            "NOT_PROVEN", "APPLY_AUTHORIZED", "NO_UPLINK_NO_HOST_IP_NO_DEFAULT_GATEWAY",
        ):
            self.assertIn(identifier, src)
        for forbidden in (
            "pct set", "pct reboot", "pct stop", "pct start",
            "ip link add", "ip addr add", "ip route add",
            "ifreload -a", "systemctl restart",
            "nft add", "iptables -A", "networkctl reload",
            "ollama pull", "/api/generate", "/api/tags",
            "Document.objects", "podman restart",
        ):
            self.assertNotIn(forbidden, src)

    def test_overlap_detects_cidr_conflicts_and_skips_default_route(self):
        sample = [{"addr_info": [{"family": "inet",
                                  "local": "172.30.110.3", "prefixlen": 28}]}]
        self.assertTrue(bridge.network_overlaps(sample, []))
        self.assertFalse(bridge.network_overlaps(
            [{"addr_info": [{"family": "inet",
                             "local": "192.168.20.225", "prefixlen": 24}]}],
            [{"dst": "default"}, {"dst": "192.168.20.0/24"}],
        ))
        self.assertTrue(bridge.network_overlaps(
            [{"addr_info": []}], [{"dst": "172.30.0.0/16"}],
        ))
        self.assertIsNone(bridge.network_overlaps(None, []))
        self.assertIsNone(bridge.network_overlaps([{"addr_info": []}],
                                                  [{"gateway": "10.0.0.1"}]))
        self.assertEqual(bridge.classification([False, False]),
                         "NO_OVERLAP_IN_SCOPED_ROUTES")
        self.assertEqual(bridge.classification([True, False]), "OVERLAP_FOUND")
        self.assertEqual(bridge.classification([None, False]), "UNVERIFIED")

    def test_bridge_device_classification_never_proves_no_leaks(self):
        with mock.patch.object(bridge, "read_command", return_value='[{"ifname":"vmbr1"}]'):
            self.assertEqual(bridge.kernel_bridge_exists(), "ABSENT")
        with mock.patch.object(bridge, "read_command", return_value='[{"ifname":"vmbr90"}]'):
            self.assertEqual(bridge.kernel_bridge_exists(), "EXISTS")
        with mock.patch.object(bridge, "read_command", return_value=None):
            self.assertEqual(bridge.kernel_bridge_exists(), "UNVERIFIED")

    def test_playbook_has_one_no_log_read_only_remote_command(self):
        src = PLAY.read_text()
        play = yaml.safe_load(src)[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        self.assertIn("BRIDGE_CANDIDATE", src)
        self.assertIn("SUBNET_CLEARANCE", src)
        self.assertIn("APPLY_AUTHORIZED", src)
        cmds = [t for t in play["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(cmds), 1)
        self.assertTrue(cmds[0]["no_log"])
        self.assertFalse(cmds[0]["changed_when"])
        self.assertFalse(cmds[0]["failed_when"])
        for task in play["tasks"]:
            assertions = task.get("ansible.builtin.assert", {})
            for condition in assertions.get("that", []):
                self.assertIsInstance(condition, str)

    def test_document_requires_separate_approval_and_nonwildcard_ollama(self):
        doc = (ROOT / "docs/BERGEN-AI-PRIVATE-PROXMOX-BRIDGE.md").read_text()
        self.assertIn("bridge-ports none", doc)
        self.assertIn("172.30.110.0/28", doc)
        self.assertIn("kein physischer Uplink", doc)
        self.assertIn("OLLAMA_HOST=0.0.0.0", doc)
        self.assertIn("Roll", doc)
        self.assertIn("LXC 120", doc)
        self.assertIn("aus", doc)
