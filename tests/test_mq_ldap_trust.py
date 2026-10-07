"""Offline checks for the LDAP trust input and preservation guard."""
from pathlib import Path
import hashlib
import re
import ssl
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class LDAPTrust(unittest.TestCase):
    def test_reviewed_root_and_valid_self_signature(self):
        cert = ROOT / 'ansible/roles/mq_lab/files/isrg-root-x2.crt'
        der = ssl.PEM_cert_to_DER_cert(cert.read_text())
        self.assertEqual(hashlib.sha256(der).hexdigest(),
                         '69729b8e15a86efc177a57afb7171dfc64add28c2fca8cf1507e34453ccb1470')
        subprocess.run(['openssl', 'verify', '-check_ss_sig', '-CAfile', str(cert), str(cert)],
                       check=True, capture_output=True)

    def test_preservation_guard_detects_changed_values(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/mq-ldap-trust.yml').read_text())[0]
        task = next(t for t in play['tasks'] if t['name'].startswith('Verify queue manager identity'))
        expression = task['ansible.builtin.assert']['that'][0]
        pattern = re.search(r"regex_findall\('([^']+)'\)", expression).group(1)
        before = 'QMNAME(A) CONNAUTH(OS) SSLKEYR(/run/key)'
        for after in ['QMNAME(B) CONNAUTH(OS) SSLKEYR(/run/key)',
                      'QMNAME(A) CONNAUTH(LDAP) SSLKEYR(/run/key)',
                      'QMNAME(A) CONNAUTH(OS) SSLKEYR(/other/key)']:
            self.assertNotEqual(re.findall(pattern, before), re.findall(pattern, after))


if __name__ == '__main__':
    unittest.main()
