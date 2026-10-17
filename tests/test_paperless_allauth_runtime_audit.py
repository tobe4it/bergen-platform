"""Safety contract for non-mutating effective allauth/OIDC timeout inspection."""
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"ansible/playbooks/audit-paperless-allauth-timeout-readonly.yml"
DOC=ROOT/"docs/PAPERLESS-ALLAUTH-TIMEOUT-AUDIT.md"

class AllauthAuditContract(unittest.TestCase):
    def test_existing_backend_identity_is_verified_first(self):
        plays=yaml.safe_load(FILE.read_text())
        self.assertEqual(plays[0]["import_playbook"], "audit-paperless-existing-backend-readonly.yml")
        self.assertEqual(plays[1]["hosts"], "venombox")
        self.assertTrue(plays[1]["become"])

    def test_only_readonly_approved_modules_and_no_log(self):
        plays=yaml.safe_load(FILE.read_text())
        tasks=plays[1]["tasks"]
        self.assertEqual(len(tasks),3)
        for task in tasks:
            modules=[k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules),1)
            self.assertIn(modules[0],{"ansible.builtin.command","ansible.builtin.assert","ansible.builtin.debug"})
        cmd=tasks[0]
        self.assertIs(cmd["changed_when"],False)
        self.assertTrue(cmd["no_log"])
        self.assertTrue(tasks[1]["no_log"])
        argv=cmd["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:5],["pct","exec","126","--","podman"])
        self.assertIn("REQUESTS_TIMEOUT",argv[-1])
        self.assertIn("allauth.socialaccount",argv[-1])
        self.assertIn("FIFTEEN_SECONDS",argv[-1])

    def test_no_restart_or_modification_and_no_username_logging(self):
        text=FILE.read_text()
        for forbidden in ("systemctl restart","systemd_service","ansible.builtin.copy",
                          "ansible.builtin.template","ansible.builtin.file","ansible.builtin.blockinfile",
                          "SOCIALACCOUNT_REQUESTS_TIMEOUT = 15","write_text("):
            self.assertNotIn(forbidden,text)
        self.assertIn("TIMEOUT_CHANGE_NOT_AUTHORIZED=true",text)
        self.assertIn("NO_SETTINGS_OR_SERVICES_CHANGED=true",text)
        self.assertNotIn("thebergens.net",text)
        self.assertNotIn("192.168.",text)

    def test_docs_do_not_claim_applied_timeout(self):
        doc=DOC.read_text()
        self.assertIn("nicht nachgewiesen",doc)
        self.assertIn("ReadTimeout",doc)
        self.assertIn("2FA",doc)
        self.assertIn("Read-only",doc) if "Read-only" in doc else self.assertIn("nur lesend",doc)

if __name__=="__main__":
    unittest.main()
