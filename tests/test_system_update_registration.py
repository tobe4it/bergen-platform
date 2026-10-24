import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import register_system_update_hosts as r
import system_updates as u


class RegistrationTests(unittest.TestCase):
    def config(self):
        return {'inventories': ['base.yml'], 'ansible_inventory': 'ansible-inventory',
                'ansible_playbook': 'ansible-playbook', 'state_dir': '/tmp/example', 'policies': {},
                'smtp': {'host': 'smtp.invalid', 'port': 587, 'username': 'example',
                         'password_file': '/tmp/password', 'sender': 'a@example.invalid',
                         'recipient': 'b@example.invalid'}}

    def test_registration_is_audit_only_and_idempotent(self):
        additions = [('mx1', 'one.example.invalid'), ('mx2', 'two.example.invalid')]
        config, overlay = r.registration(self.config(), {}, {}, additions, ['mx1', 'mx2', 'mx3'],
                                         'operator', 22, Path('/tmp/extra.json'))
        self.assertTrue(all(p['mode'] == 'audit' for p in config['policies'].values()))
        same, hosts = r.registration(config, overlay, overlay, additions, ['mx1', 'mx2', 'mx3'],
                                     'operator', 22, Path('/tmp/extra.json'))
        self.assertEqual((same, hosts), (config, overlay))
        missing = u.missing_required_hosts(config, overlay)
        self.assertEqual([h['host'] for h in missing], ['mx3'])
        self.assertEqual(u.overall({'hosts': missing}), 'FEHLER')

    def test_existing_alias_cannot_be_silently_retargeted(self):
        with self.assertRaisesRegex(ValueError, 'DIFFERENT_SSH_SETTINGS'):
            r.registration(self.config(), {'mx1': {'ansible_host': 'other.invalid'}}, {},
                           [('mx1', 'one.invalid')], ['mx1'], 'operator', 22, Path('/tmp/extra.json'))

    def test_missing_required_host_defers_all_security_installations(self):
        config = {'required_hosts': ['missing'], 'policies': {'one': {'mode': 'security'}}, 'canaries': ['one']}
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'run_host', return_value={'status': 'OK'}) as run:
            result = u.process_hosts(config, ['one'], Path(temp))
        self.assertFalse(run.call_args.args[3])
        self.assertIn('deferred', result[0])

    @unittest.skipUnless(shutil.which('ansible-inventory'), 'ansible-inventory required')
    def test_json_overlay_is_loaded_by_real_ansible_inventory(self):
        _, hosts = r.registration(self.config(), {}, {}, [('mx1', 'one.example.invalid')],
                                  ['mx1'], 'operator', 22, Path('/tmp/extra.json'))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'extra-update-hosts.json'
            path.write_text(json.dumps({'all': {'children': {'external_mail_nodes': {'hosts': hosts}}}}))
            ansible_config = Path(temp) / 'ansible.cfg'
            ansible_config.write_text('[defaults]\n')
            result = subprocess.run([shutil.which('ansible-inventory'), '-i', str(path), '--list'],
                                    cwd=temp, capture_output=True, text=True, timeout=30,
                                    env={**os.environ, 'ANSIBLE_CONFIG': str(ansible_config)})
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)['_meta']['hostvars']['mx1']
            self.assertEqual(actual['ansible_host'], 'one.example.invalid')
            self.assertEqual(actual['ansible_user'], 'operator')


if __name__ == '__main__':
    unittest.main()
