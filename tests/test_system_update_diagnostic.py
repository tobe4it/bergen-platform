import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


callback = load('diagnostic', 'ansible/callback_plugins/bergen_update_diagnostic.py')
runner = load('runner', 'scripts/system_updates.py')


class DiagnosticTests(unittest.TestCase):
    def test_error_categories_never_return_raw_credentials_or_endpoints(self):
        for message, expected in [
            ('Permission denied (publickey,password) SECRET', 'SSH_AUTHENTICATION_FAILED'),
            ('Host key verification failed SECRET', 'SSH_HOST_KEY_FAILED'),
            ('Could not resolve hostname SECRET', 'HOST_RESOLUTION_FAILED'),
            ('Connection refused SECRET', 'CONNECTION_REFUSED'),
            ('Connection timed out SECRET', 'CONNECTION_TIMEOUT'),
            ('Missing sudo password SECRET', 'BECOME_FAILED'),
            ('The module requires a minimum of Python 3.8 SECRET', 'PYTHON_ENVIRONMENT_FAILED'),
            ('Failed to fetch https://user:SECRET@example.invalid 401 Unauthorized', 'REPOSITORY_AUTHENTICATION_FAILED'),
            ('PYTHON3_APT_REQUIRED', 'PYTHON3_APT_REQUIRED'),
            ('NO_TRUSTED_SECURITY_SUITE_IN_CACHE', 'NO_TRUSTED_SECURITY_SUITE_IN_CACHE'),
        ]:
            with self.subTest(message=message):
                self.assertEqual(callback.classify({'msg': message}), expected)
        self.assertEqual(callback.classify({'msg': 'SECRET', '_ansible_no_log': True}), 'ERROR_DETAILS_REDACTED')
        self.assertEqual(callback.classify({'assertion': "ansible_facts.pkg_mgr == 'apt' or system_updates_dnf_metadata_verified | bool"}),
                         'DNF_SECURITY_METADATA_NOT_VERIFIED')
        self.assertEqual(callback.classify({'module_results': {'setup': {'msg': 'Missing sudo password SECRET'}}}),
                         'BECOME_FAILED')

    def test_frame_parser_rejects_ambiguous_frames_and_never_copies_messages(self):
        event = {'host': 'target', 'task': 'Read operating system facts', 'code': 'BECOME_FAILED',
                 'msg': 'password=SECRET', 'kind': 'FAILED', 'rc': 1}
        frame = callback.PREFIX + json.dumps([event])
        details = runner.failure_details(frame, 'target')
        self.assertEqual(details['failure_code'], 'BECOME_FAILED')
        self.assertNotIn('SECRET', json.dumps(details))
        self.assertEqual(runner.failure_details(frame + '\n' + frame, 'target'), {})
        self.assertEqual(runner.failure_details(frame, 'other'), {})

    def test_mail_contains_task_code_and_no_generic_timeout_claim(self):
        report = {'run_id': 'test', 'started': 'now', 'finished': 'now', 'commit': 'test',
                  'config_sha256': 'test', 'mode': 'AUDIT_ONLY', 'hosts': [{
                      'host': 'target', 'status': 'FAILED', 'reason': 'TASK_FAILED',
                      'failed_task': 'Read operating system facts', 'failure_code': 'BECOME_FAILED'}]}
        _, plain, body = runner.render(report)
        self.assertIn('Read operating system facts', plain)
        self.assertIn('BECOME_FAILED', plain)
        self.assertIn('BECOME_FAILED', body)
        self.assertNotIn('Transaktionszustand', plain)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
    def test_real_rescued_failure_produces_bounded_callback_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'play.yml'
            path.write_text(json.dumps([{'hosts': 'target', 'gather_facts': False, 'tasks': [{
                'block': [{'name': 'Select or apply trusted distribution security fixes',
                           'ansible.builtin.fail': {'msg': 'PYTHON3_APT_REQUIRED'}}],
                'rescue': [{'ansible.builtin.debug': {'msg': 'password=SECRET_DO_NOT_PRINT'}}]
            }]}]))
            result = subprocess.run([shutil.which('ansible-playbook'), '-i', 'target,', '-c', 'local', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=30,
                                    env={**os.environ, 'ANSIBLE_STDOUT_CALLBACK': 'bergen_update_diagnostic',
                                         'ANSIBLE_CALLBACK_PLUGINS': str(ROOT / 'ansible/callback_plugins')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('SECRET_DO_NOT_PRINT', result.stdout + result.stderr)
            details = runner.failure_details(result.stdout, 'target')
            self.assertEqual(details['failure_code'], 'PYTHON3_APT_REQUIRED')
            self.assertEqual(details['failed_task'], 'Select or apply trusted distribution security fixes')


if __name__ == '__main__':
    unittest.main()
