"""Read-only existing-backend preflight must never provision services."""
import unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
PLAY=ROOT/"ansible/playbooks/audit-paperless-existing-backend-readonly.yml"
class PaperlessExistingBackendTest(unittest.TestCase):
    def test_readonly_proxmox_pinned_guest_audit(self):
        doc=yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(doc),1)
        self.assertEqual(doc[0]["hosts"],"venombox")
        for t in doc[0]["tasks"]:
            mods=[k for k in t if k.startswith("ansible.builtin.")]
            self.assertEqual(len(mods),1)
            self.assertIn(mods[0],{"ansible.builtin.command","ansible.builtin.assert","ansible.builtin.debug"})
            if mods[0]=="ansible.builtin.command":
                self.assertIs(t["changed_when"],False)
        text=PLAY.read_text()
        self.assertIn("PAPERLESS_EXISTING_BACKEND_READONLY_OK",text)
        self.assertIn("backup=1(,|$)",text)
        self.assertNotIn("podman pull",text)
        self.assertNotIn("systemctl start",text)
