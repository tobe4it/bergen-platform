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
EXTENDED_SCRIPT = ROOT / "ansible/files/bergen_ai/audit_private_bridge_extended_networks.py"
EXTENDED_PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-private-bridge-extended-readonly.yml"
WG_SCRIPT = ROOT / "ansible/files/bergen_ai/audit_private_bridge_wg_prefixes_readonly.py"
WG_PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-private-bridge-wg-readonly.yml"

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

spec_extended = importlib.util.spec_from_file_location("bergen_ai_extended_net", EXTENDED_SCRIPT)
extended = importlib.util.module_from_spec(spec_extended)
spec_extended.loader.exec_module(extended)


class ExtendedBridgeAuditTest(TestCase):
    def test_extended_script_is_no_write_and_rejects_overlap(self):
        text = EXTENDED_SCRIPT.read_text()
        ast.parse(text, filename=str(EXTENDED_SCRIPT))
        self.assertEqual(str(extended.CANDIDATE), "172.30.110.0/28")
        self.assertIn('podman", "network", "inspect"', text)
        self.assertIn('["pct", "list"]', text)
        self.assertIn('run(["pct", "config", vmid]', text)
        self.assertIn('FULL_NETWORK_CLEARANCE="NOT_PROVEN"', text)
        self.assertIn('APPLY_AUTHORIZED=False', text)
        for forbidden in ("pct set", "pct start", "pct reboot",
                          "ip link add", "ip addr add", "nft add",
                          "iptables -A", "systemctl restart",
                          "podman run", "podman network create",
                          "/api/generate", "/api/tags"):
            self.assertNotIn(forbidden, text)

    def test_extended_overlap_classifies_addresses_routes_and_static_guest_configs(self):
        self.assertTrue(extended.overlaps_address_routes(
            [{"addr_info": [{"family": "inet", "local": "172.30.110.5", "prefixlen": 28}]}], []))
        self.assertFalse(extended.overlaps_address_routes(
            [{"addr_info": [{"family": "inet", "local": "192.168.20.225", "prefixlen": 24}]}],
            [{"dst": "default"}]))
        self.assertTrue(extended.overlaps_address_routes(
            [{"addr_info": []}], [{"dst": "172.30.110.0/24"}]))
        self.assertIsNone(extended.overlaps_address_routes(None, []))
        with mock.patch.object(extended, "run", return_value="net0: name=eth0,bridge=vmbr1,ip=172.30.110.5/28"):
            self.assertTrue(extended.static_lxc_overlap("110"))
        with mock.patch.object(extended, "run", return_value="net0: name=eth0,bridge=vmbr1,ip=dhcp"):
            self.assertFalse(extended.static_lxc_overlap("110"))

    def test_extended_playbook_cannot_activate_bridge(self):
        document = yaml.safe_load(EXTENDED_PLAY.read_text())[0]
        self.assertEqual(document["hosts"], "venombox")
        self.assertFalse(document["gather_facts"])
        tasks = document["tasks"]
        commands = [t for t in tasks if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0]["no_log"])
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        text = EXTENDED_PLAY.read_text()
        self.assertIn("FULL_NETWORK_CLEARANCE=NOT_PROVEN", text)
        self.assertIn("not extended_report.APPLY_AUTHORIZED", text)
        self.assertIn("NETWORKS", text)

spec_wg = importlib.util.spec_from_file_location("bergen_ai_private_wg", WG_SCRIPT)
wg = importlib.util.module_from_spec(spec_wg)
spec_wg.loader.exec_module(wg)


class WireGuardPrefixAuditTest(TestCase):
    def test_wg_source_is_readonly_and_does_not_log_peers(self):
        src = WG_SCRIPT.read_text()
        ast.parse(src, filename=str(WG_SCRIPT))
        self.assertEqual(str(wg.CANDIDATE), "172.30.110.0/28")
        self.assertIn('["wg","show","all","allowed-ips"]', src)
        self.assertIn('FULL_NETWORK_CLEARANCE="NOT_PROVEN"', src)
        self.assertIn('APPLY_AUTHORIZED=False', src)
        self.assertIn('INACTIVE_WG_TUNNELS="NOT_INSPECTED"', src)
        for forbidden in ("wg set", "wg-quick up", "wg-quick down", "PrivateKey",
                          "nft add", "iptables -A", "pct set", "pct reboot",
                          "ip link add", "/api/generate", "ollama run"):
            self.assertNotIn(forbidden, src)

    def test_wg_result_requires_complete_scoped_read(self):
        self.assertEqual(wg.summarize(["NOT_INSTALLED", "NO_ACTIVE_PEER_PREFIXES"]),
                         "NO_OVERLAP_IN_INSPECTED_LIVE_WG_PEERS")
        self.assertEqual(wg.summarize(["NO_OVERLAP_IN_ACTIVE_PEERS", "UNVERIFIED"]),
                         "INCOMPLETE")
        self.assertEqual(wg.summarize(["UNVERIFIED", "OVERLAP_FOUND"]),
                         "OVERLAP_FOUND")
        self.assertEqual(wg.parse_frame(
            'BERGEN_AI_WG_GUEST_V1:{"state":"OVERLAP_FOUND"}'),
            "OVERLAP_FOUND")
        self.assertEqual(wg.parse_frame(
            'BERGEN_AI_WG_GUEST_V1:{"state":"MALFORMED"}'),
            "UNVERIFIED")
        self.assertEqual(wg.parse_frame(
            'BERGEN_AI_WG_GUEST_V1:{"state":"NO_ACTIVE_PEER_PREFIXES"}\n'
            'BERGEN_AI_WG_GUEST_V1:{"state":"NO_ACTIVE_PEER_PREFIXES"}'),
            "UNVERIFIED")

    def test_wg_playbook_keeps_gateway_and_auth_out_of_scope(self):
        content = WG_PLAY.read_text()
        doc = yaml.safe_load(content)[0]
        self.assertEqual(doc["hosts"], "venombox")
        self.assertFalse(doc["gather_facts"])
        self.assertIn("FULL_NETWORK_CLEARANCE=NOT_PROVEN", content)
        self.assertIn("INACTIVE_WG_TUNNELS=NOT_INSPECTED", content)
        commands = [t for t in doc["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        self.assertFalse(commands[0]["changed_when"])
        self.assertFalse(commands[0]["failed_when"])
        self.assertTrue(commands[0]["no_log"])
        for task in doc["tasks"]:
            for cond in task.get("ansible.builtin.assert", {}).get("that", []):
                self.assertIsInstance(cond, str)
