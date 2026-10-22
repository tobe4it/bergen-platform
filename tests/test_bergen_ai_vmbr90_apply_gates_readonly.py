"""Offline security contract for vmbr90 blocked-gates diagnostic playbook."""
from pathlib import Path
from unittest import TestCase

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-vmbr90-apply-gates-readonly.yml"


class Vmbr90GateAuditTests(TestCase):
    def test_only_audits_and_no_mutating_tasks(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual([p["import_playbook"] for p in plays[:4]], [
            "audit-bergen-ai-private-bridge-external-gates-readonly.yml",
            "audit-bergen-ai-private-bridge-readonly.yml",
            "audit-bergen-ai-private-bridge-extended-readonly.yml",
            "audit-bergen-ai-private-bridge-wg-readonly.yml",
        ])
        last = plays[4]
        self.assertEqual(last["hosts"], "venombox")
        self.assertTrue(last["become"])
        self.assertFalse(last["gather_facts"])
        for task in last["tasks"]:
            self.assertTrue(set(task).intersection({"ansible.builtin.command",
                                                  "ansible.builtin.assert",
                                                  "ansible.builtin.set_fact",
                                                  "ansible.builtin.debug",
                                                  "name", "register", "no_log",
                                                  "changed_when", "failed_when",
                                                  "check_mode"}))
            assert not any(
                key in task for key in ("ansible.builtin.copy",
                                        "ansible.builtin.file",
                                        "ansible.builtin.shell",
                                        "ansible.builtin.service",
                                        "ansible.builtin.template"))
        commands = [t for t in last["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertFalse(cmd["changed_when"])
        self.assertTrue(cmd["no_log"])
        self.assertEqual(cmd["ansible.builtin.command"]["argv"][:2],
                         ["python3", "-c"])
        self.assertIn("preflight_vmbr90_scoped_apply_readonly.py",
                      cmd["ansible.builtin.command"]["argv"][2])
        assert all(t.get("no_log") for t in last["tasks"]
                   if "ansible.builtin.set_fact" in t)

    def test_every_mutating_apply_precondition_is_diagnosed(self):
        text = PLAY.read_text()
        for key in ("IPAM_DECLARED_RANGES", "IPAM_SCOPE_COMPLETE",
                    "BRIDGE_UNUSED", "CT110_CT126_CT120_NIC_BASELINE",
                    "LXC_PODMAN_NETWORK_RANGES", "LIVE_WIREGUARD_RANGES",
                    "HOST_AND_CT_CONFIG_READABLE", "BACKUP_NFS",
                    "CT110_RECENT_BACKUP_METADATA", "CT126_RECENT_BACKUP_METADATA",
                    "HOST_IFUPDOWN2_DROPIN_PRECHECK",
                    "CT110_CT126_RUNNING_NET0_ONLY"):
            self.assertIn(key, text)
        self.assertIn("APPLY_AUTHORIZED=False", text)
        self.assertIn("OPERATOR_APPROVAL=NOT_REQUESTED_IN_READ_ONLY_AUDIT", text)
        self.assertIn("INDEPENDENT_CONSOLE_ACCESS=NOT_ATTESTED_BY_THIS_AUDIT", text)
        for forbidden in ("pct, set", "ifup, vmbr90", "ifdown, vmbr90",
                          "ifreload -a", "--net1", "--net0", "rm -rf",
                          "systemctl restart", "APPROVE_SCOPED_VMBR90_CT110_CT126"):
            self.assertNotIn(forbidden, text)

    def test_no_sensitive_source_fields_are_printed(self):
        text = PLAY.read_text()
        debug = text.split("name: Emit no-write operator-review status")[1]
        self.assertNotIn("rollback_gate.CT110_CONFIG", debug)
        self.assertNotIn("ipam_gate.SOURCE_QUALITY", debug)
        self.assertNotIn("hostvars['localhost'].ipam_gate.STATUS", debug)
        self.assertNotIn("scoped_vmbr90_gate_raw.stdout", debug)
