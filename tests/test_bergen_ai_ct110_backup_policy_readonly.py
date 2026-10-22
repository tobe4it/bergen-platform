"""Offline tests for Bergen-AI CT110 read-only backup policy audit."""
import ast
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ansible/files/bergen_ai/audit_ct110_backup_policy_readonly.py"
PLAYBOOK = ROOT / "ansible/playbooks/audit-bergen-ai-ct110-backup-policy-readonly.yml"
spec = importlib.util.spec_from_file_location("bridge_ct110_backup_policy", SCRIPT)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class CT110BackupPolicyTest(TestCase):
    def test_guest_identity_and_mounts_classified_only(self):
        cfg = (
            "hostname: bergen-ai\n"
            "rootfs: disk:subvol-110-disk-0,size=12G\n"
            "net0: name=eth0,bridge=vmbr1\n"
            "mp0: /srv/ai/open-webui,mp=/srv/open-webui\n"
        )
        self.assertEqual(policy.inspect_mounts(cfg), (
            "CONFIGURED", "BIND_PRESENT", "ONE_OR_MORE_UNSET_OR_DISABLED"))
        self.assertEqual(policy.inspect_mounts(
            "hostname: bergen-ai\nrootfs: local:subvol-110\n"), (
            "CONFIGURED", "NONE", "NO_EXTRA_MOUNTS"))
        self.assertEqual(policy.inspect_mounts(
            "hostname: bergen-ai\nrootfs: local:subvol-110\n"
            "mp0: local:subvol-110-disk-1,mp=/data,backup=1\n"), (
            "CONFIGURED", "VOLUME_MOUNTS_ONLY", "ALL_EXPLICIT_BACKUP_1"))
        self.assertEqual(policy.inspect_mounts(
            "hostname: wrong\nrootfs: local:subvol-110\n")[0], "UNVERIFIED")
        self.assertEqual(policy.inspect_mounts(None)[0], "UNVERIFIED")

    def test_vmid_spec_is_bounded_and_ranges_are_matched(self):
        self.assertTrue(policy.vmid_in_spec("100-120,130"))
        self.assertTrue(policy.vmid_in_spec("110,126"))
        self.assertFalse(policy.vmid_in_spec("126,130"))
        self.assertIsNone(policy.vmid_in_spec("126,foo"))
        self.assertIsNone(policy.vmid_in_spec("125-110"))
        self.assertIsNone(policy.vmid_in_spec(""))

    def test_backup_schedule_pve_selection_is_not_effectiveness(self):
        explicit = [{"vmid": "110,126", "enabled": 1, "node": "venombox"}]
        self.assertEqual(policy.audit_jobs(explicit),
                         ("EXPLICIT_VMID_SELECTION", 1))
        every = [{"all": 1, "exclude": "200", "node": "venombox"}]
        self.assertEqual(policy.audit_jobs(every),
                         ("ALL_GUESTS_SELECTION", 1))
        exclusion = [{"all": 1, "exclude": "110", "node": "venombox"}]
        self.assertEqual(policy.audit_jobs(exclusion),
                         ("NO_MATCH_IN_VISIBLE_PVE_JOBS", 1))
        disabled = [{"vmid": "110", "enabled": 0}]
        self.assertEqual(policy.audit_jobs(disabled),
                         ("NO_MATCH_IN_VISIBLE_PVE_JOBS", 1))
        othernode = [{"all": 1, "node": "somewhere-else"}]
        self.assertEqual(policy.audit_jobs(othernode),
                         ("NO_MATCH_IN_VISIBLE_PVE_JOBS", 1))
        pool = [{"pool": "ai"}]
        self.assertEqual(policy.audit_jobs(pool),
                         ("SELECTION_UNRESOLVED", 1))
        unknown = [{"vmid": "110,not-numeric"}]
        self.assertEqual(policy.audit_jobs(unknown),
                         ("SELECTION_UNRESOLVED", 1))
        self.assertEqual(policy.audit_jobs(None),
                         ("UNVERIFIED", "UNVERIFIED"))

    def test_script_and_playbook_deny_automatic_changes(self):
        text = SCRIPT.read_text()
        ast.parse(text)
        self.assertIn('APPLY_AUTHORIZED=False', text)
        self.assertIn('CT110_RESTORE_VALIDATED=False', text)
        for forbidden in ("pct set", "pct start", "pct stop", "pct reboot",
                          "vzdump --", "pvesh set", "pvesh create",
                          "qmrestore", "pct restore", "systemctl restart",
                          "ifreload", "ip link add", "os.unlink", "rm -rf"):
            self.assertNotIn(forbidden, text)
        play = yaml.safe_load(PLAYBOOK.read_text())[0]
        self.assertEqual(play["hosts"], "venombox")
        self.assertTrue(play["become"])
        self.assertFalse(play["gather_facts"])
        cmds = [x for x in play["tasks"] if "ansible.builtin.command" in x]
        self.assertEqual(len(cmds), 1)
        self.assertFalse(cmds[0]["changed_when"])
        self.assertFalse(cmds[0]["failed_when"])
        self.assertTrue(cmds[0]["no_log"])
        self.assertIn("not policy_gate.APPLY_AUTHORIZED", PLAYBOOK.read_text())
