"""Static safety contracts for the site-driven Paperless DRF ACL audit."""
import unittest
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
PLAY=ROOT/"ansible/playbooks/audit-paperless-effective-drf-readonly.yml"
EX=ROOT/"docs/examples/paperless-acl.local.yml.example"
DOC=ROOT/"docs/PAPERLESS-DRF-EFFECTIVE-AUDIT.md"

class PaperlessDRFContract(unittest.TestCase):
    def test_thirty_six_site_driven_checks_without_private_users_in_git(self):
        p=yaml.safe_load(PLAY.read_text())[0]
        self.assertEqual(p["hosts"],"venombox")
        tasks=p["tasks"]
        runner=next(t for t in tasks if "Run authorization matrix" in t["name"])
        code=runner["ansible.builtin.command"]["argv"][-1]
        self.assertIn("json.loads({{ paperless_acl_expected_cases | to_json | to_json }})",code)
        self.assertIn("total != 36",code)
        self.assertIn("len(ids) != 4",code)
        self.assertIn("len(names) != 3",code)
        self.assertIn("not any",code)
        self.assertNotIn("thomas",code.lower())
        self.assertNotIn("nadja",code.lower())
        self.assertTrue(runner["no_log"])
        self.assertIs(runner["changed_when"],False)
        self.assertNotIn("force_login",code)
        self.assertIn("force_authenticate",code)
        self.assertIn("HTTP_HOST='127.0.0.1'",code)
    def test_synthetic_matrix_only_and_sensitive_input_ignored(self):
        data=yaml.safe_load(EX.read_text())["paperless_acl_expected_cases"]
        self.assertEqual(len(data),12)
        self.assertEqual(len({x["document_id"] for x in data}),4)
        self.assertEqual(len({x["username"] for x in data}),3)
        self.assertIn("ansible/vars/paperless*.local.yml",(ROOT/".gitignore").read_text())
        self.assertIn("OIDC",DOC.read_text())
    def test_no_unexpected_write_operations(self):
        tasks=yaml.safe_load(PLAY.read_text())[0]["tasks"]
        allow={"ansible.builtin.assert","ansible.builtin.command","ansible.builtin.debug"}
        for task in tasks:
            modules=[x for x in task if x.startswith("ansible.builtin.")]
            self.assertEqual(len(modules),1)
            self.assertIn(modules[0],allow)
        self.assertNotIn("--apply",PLAY.read_text())
        self.assertNotIn("delete_document",PLAY.read_text())
        self.assertNotIn("post(",PLAY.read_text())
        self.assertNotIn("put(",PLAY.read_text())
        self.assertNotIn("patch(",PLAY.read_text())
