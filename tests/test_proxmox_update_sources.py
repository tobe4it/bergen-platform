import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('source_repair', Path(__file__).resolve().parents[1] / 'scripts/repair_proxmox_update_sources.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sources():
    return {name: 'Types: deb\nURIs: ' + uri + '\nSuites: trixie\nComponents: ' + component + '\nSigned-By: /usr/share/keyrings/proxmox-archive-keyring.gpg\n'
            for name, uri, component in [
                ('pve-enterprise.sources', 'https://enterprise.proxmox.com/debian/pve', 'pve-enterprise'),
                ('pve-no-subscription.sources', 'http://download.proxmox.com/debian/pve', 'pve-no-subscription'),
                ('ceph.sources', 'https://enterprise.proxmox.com/debian/ceph-squid', 'enterprise')]}


class RepairTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
    def test_full_script_transport_and_failed_remote_evidence_through_real_ansible(self):
        # Force a refusal before any source reads/writes, even on a real PVE host.
        code = 'import os\nos.geteuid = lambda: 1\n' + Path(m.__file__).read_text()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            capture = directory / 'result.json'
            play = m.build_play(code, capture)
            play[0]['become'] = False
            play[0]['vars'] = {'ansible_python_interpreter': sys.executable}
            path = directory / 'repair.yml'
            path.write_text(json.dumps(play))
            result = subprocess.run([
                shutil.which('ansible-playbook'), '-i', 'venombox,', '-c', 'local', str(path)
            ], cwd=m.ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(capture.read_text())
            remote = json.loads(evidence['stdout'])
            self.assertEqual(evidence['rc'], 1)
            self.assertEqual(remote['status'], 'FAILED')
            self.assertEqual(remote['error'], 'ROOT_REQUIRED')
            self.assertEqual(remote['source_changes'], [])
            self.assertEqual(capture.stat().st_mode & 0o777, 0o600)

    def test_change_email_uses_verified_tls_and_stops_before_login_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            password = directory / 'password'
            password.write_text('SECRET')
            password.chmod(0o600)
            config = {'smtp': {'host': 'smtp.invalid', 'port': 587,
                      'password_file': str(password), 'username': 'user',
                      'sender': 'sender@example.invalid', 'recipient': 'recipient@example.invalid'}}
            evidence = {'run_id': 'test', 'commit': 'abc', 'started': 'now', 'finished': 'now',
                        'result': {'status': 'FAILED', 'error': 'APT_METADATA_REFRESH_FAILED'}}
            with patch.object(m.smtplib, 'SMTP') as factory:
                smtp = factory.return_value.__enter__.return_value
                smtp.starttls.side_effect = m.ssl.SSLError('failure')
                with self.assertRaises(m.ssl.SSLError):
                    m.send(config, evidence, directory)
                smtp.login.assert_not_called()
                smtp.send_message.assert_not_called()
                self.assertTrue(smtp.starttls.call_args.kwargs['context'].check_hostname)
            with patch.object(m.smtplib, 'SMTP') as factory:
                smtp = factory.return_value.__enter__.return_value
                smtp.send_message.return_value = {}
                m.send(config, evidence, directory)
                message = smtp.send_message.call_args.args[0]
                self.assertNotIn('SECRET', message.as_string())
                self.assertIn('[FEHLER]', message['Subject'])
                self.assertEqual(message['To'], 'recipient@example.invalid')

    def test_remote_command_entrypoint_without_file_or_proxmox_is_safe(self):
        result = subprocess.run([sys.executable, '-c', Path(m.__file__).read_text(), '--remote'],
                                env={**os.environ, 'PATH': '/nonexistent'},
                                capture_output=True, text=True, timeout=10)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['source_changes'], [])
        self.assertFalse(report['packages_installed'])

    def test_only_two_files_change_and_second_run_has_no_changes(self):
        original = sources()
        plan = m.source_plan(original)
        self.assertEqual(set(plan), {'pve-enterprise.sources', 'ceph.sources'})
        self.assertIn('Enabled: no', plan['pve-enterprise.sources'])
        self.assertIn('Components: no-subscription', plan['ceph.sources'])
        self.assertIn('/debian/ceph-squid', plan['ceph.sources'])
        self.assertEqual(m.source_plan({**original, **plan}), {})

    def test_no_cross_release_or_unsigned_or_mixed_channel_changes(self):
        for old, new in [('Suites: trixie', 'Suites: bookworm'),
                         ('Components: enterprise', 'Components: test'),
                         ('proxmox-archive-keyring.gpg', 'other.gpg'),
                         ('Types: deb', 'Types: deb\nTrusted: yes'),
                         ('Types: deb', 'Types: deb\nTypes: deb')]:
            text = sources()
            text['ceph.sources'] = text['ceph.sources'].replace(old, new)
            with self.subTest(new=new), self.assertRaises(ValueError):
                m.source_plan(text)

    def test_disabled_public_source_refused(self):
        for name in ('pve-no-subscription.sources', 'ceph.sources'):
            text = sources()
            text[name] += 'Enabled: no\n'
            with self.assertRaises(ValueError):
                m.source_plan(text)


if __name__ == '__main__':
    unittest.main()
