"""Offline regression tests for Bergen-AI external IPAM and rollback gates."""
import ast
import importlib.util
from pathlib import Path
import tempfile
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_private_bridge_external_gates.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-private-bridge-external-gates-readonly.yml"
EXAMPLE = ROOT / "docs/examples/bergen-ai-bridge-ipam.local.json.example"

spec = importlib.util.spec_from_file_location("bridge_external_gates", SCRIPT)
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)


def manifest(*, unifi=None, vpn=None, other=None, complete=False):
    return {"scopes": {
        "unifi": {"complete": complete, "networks": unifi or []},
        "vpn": {"complete": complete, "networks": vpn or []},
        "other_hosts": {"complete": complete, "networks": other or []},
    }}


class ExternalGatesTest(TestCase):
    def test_source_is_read_only_and_non_authorizing(self):
        src = SCRIPT.read_text()
        ast.parse(src)
        self.assertEqual(str(gates.CANDIDATE), "172.30.110.0/28")
        self.assertIn('APPLY_AUTHORIZED=False', src)\n        self.assertIn('r"^net0:\\s"', src)
        self.assertIn('FULL_NETWORK_CLEARANCE="NOT_PROVEN"', src)
        self.assertIn('ROLLBACK_CLEARANCE="NOT_PROVEN"', src)
        for forbidden in ("pct set", "pct start", "pct stop", "pct reboot",
                          "ip link add", "ip addr add", "ip route add",
                          "systemctl restart", "ifreload -a", "nft add",
                          "iptables -A", "wg set", "vzdump --",
                          "rm -rf", "shutil.copy", "os.chmod",
                          "subprocess.Popen", "curl", "requests.get"):
            self.assertNotIn(forbidden, src)

    def test_manifest_matches_all_three_scopes_and_detects_supernet(self):
        self.assertEqual(gates.audit_manifest(manifest(
            unifi=["192.168.0.0/16"], vpn=["10.9.0.0/16"],
            other=["172.30.0.0/16"]))[0], "OVERLAP_FOUND")
        status, scope, source = gates.audit_manifest(manifest(
            unifi=["192.168.20.0/24"], vpn=["10.9.1.0/24"],
            complete=True))
        self.assertEqual(status, "NO_OVERLAP_IN_DECLARED_RANGES")
        self.assertEqual(scope, "OPERATOR_DECLARED_COMPLETE")
        self.assertEqual(source, "MANUAL_INPUT_NOT_INDEPENDENTLY_VERIFIED")

    def test_default_route_is_not_treated_as_allocated_vpn_range(self):
        self.assertEqual(gates.audit_manifest(
            manifest(vpn=["0.0.0.0/0"]))[0], "VPN_CATCHALL_REVIEW")
        self.assertEqual(gates.audit_manifest(
            manifest(vpn=["0.0.0.0/0", "172.30.110.4/32"]))[0], "OVERLAP_FOUND")

    def test_missing_or_malformed_inventory_never_approves(self):
        for data in ({}, [], manifest(vpn=["invalid"]),
                     manifest(other=["172.30.110.1"]),
                     {"scopes": {"unifi": {"complete": True, "networks": []}}}):
            self.assertEqual(gates.audit_manifest(data)[0], "UNVERIFIED")
        self.assertIsNone(gates.parse_cidr("172.30.110.12"))
        self.assertIsNone(gates.parse_cidr("not-cidr"))

    def test_real_pct_net0_syntax_is_recognized_without_mutation(self):
        config_110 = (
            "arch: amd64\\n"
            "hostname: bergen-ai\\n"
            "net0: name=eth0,bridge=vmbr20,ip=dhcp,type=veth\\n"
            "unprivileged: 1\\n"
        )
        config_126 = (
            "hostname: bergen-paperless\\n"
            "net0: name=eth0,bridge=vmbr1,ip=192.168.20.12/24\\n"
        )
        with mock.patch.object(gates, "command", return_value=config_110) as query:
            self.assertEqual(gates.guest_config("110", "bergen-ai"),
                             "READABLE_SOURCE_ONLY")
            query.assert_called_once_with(["pct", "config", "110"])
        with mock.patch.object(gates, "command", return_value=config_126):
            self.assertEqual(gates.guest_config("126", "bergen-paperless"),
                             "READABLE_SOURCE_ONLY")
        with mock.patch.object(gates, "command", return_value=config_110):
            self.assertEqual(gates.guest_config("110", "wrong-host"),
                             "UNVERIFIED")
        with mock.patch.object(gates, "command", return_value="hostname: bergen-ai\\n"):
            self.assertEqual(gates.guest_config("110", "bergen-ai"),
                             "UNVERIFIED")
        with mock.patch.object(gates, "command", return_value=None):
            self.assertEqual(gates.guest_config("110", "bergen-ai"),
                             "UNVERIFIED")

    def test_backups_are_metadata_only_not_restore_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(gates, "BACKUP_ROOT", root):
                (root / "dump").mkdir()
                self.assertEqual(gates.backup_metadata("110"),
                                 "NO_RECENT_FILE_METADATA")
                (root / "dump" / "vzdump-lxc-110-2026_10_19.tar.zst").write_bytes(b"fake")
                self.assertEqual(gates.backup_metadata("110"),
                                 "RECENT_FILE_METADATA_ONLY")
                self.assertEqual(gates.backup_metadata("126"),
                                 "NO_RECENT_FILE_METADATA")

    def test_local_wg_only_scopes_peers_on_pve(self):
        with mock.patch.object(gates.shutil, "which", return_value="/usr/bin/wg"):
            with mock.patch.object(gates, "command", return_value="wg0 pubkey 172.30.110.2/32"):
                self.assertEqual(gates.local_wg_allowed_ips(), "OVERLAP_FOUND")
            with mock.patch.object(gates, "command", return_value="wg0 pubkey 0.0.0.0/0"):
                self.assertEqual(gates.local_wg_allowed_ips(), "LOCAL_CATCHALL_REVIEW")
            with mock.patch.object(gates, "command", return_value="wg0 pubkey 10.1.0.0/16"):
                self.assertEqual(gates.local_wg_allowed_ips(),
                                 "NO_OVERLAP_IN_LOCAL_WG_ALLOWED_IPS")

    def test_playbook_enforces_two_no_write_scopes_and_bounded_frames(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 2)
        self.assertEqual(plays[0]["hosts"], "localhost")
        self.assertEqual(plays[1]["hosts"], "venombox")
        self.assertFalse(plays[0]["become"])
        self.assertTrue(plays[1]["become"])
        for play in plays:
            self.assertFalse(play["gather_facts"])
            commands = [t for t in play["tasks"] if "ansible.builtin.command" in t]
            self.assertEqual(len(commands), 1)
            self.assertTrue(commands[0]["no_log"])
            self.assertFalse(commands[0]["changed_when"])
            self.assertFalse(commands[0]["failed_when"])
            for task in play["tasks"]:
                assertions = task.get("ansible.builtin.assert", {})
                for condition in assertions.get("that", []):
                    self.assertIsInstance(condition, str)
        src = PLAY.read_text()
        self.assertIn("FULL_NETWORK_CLEARANCE=NOT_PROVEN", src)
        self.assertIn("ROLLBACK_CLEARANCE=NOT_PROVEN", src)
        self.assertIn("not rollback_gate.APPLY_AUTHORIZED", src)
        self.assertIn("not ipam_gate.APPLY_AUTHORIZED", src)

    def test_operator_inventory_is_ignored_and_example_is_incomplete(self):
        import json
        data = json.loads(EXAMPLE.read_text())
        self.assertEqual(gates.audit_manifest(data)[1],
                         "OPERATOR_DECLARED_INCOMPLETE")
        self.assertIn("ansible/vars/bergen-ai-bridge-ipam.local.json",
                      (ROOT / ".gitignore").read_text())
