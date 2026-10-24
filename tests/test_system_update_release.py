import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import system_updates as u
import release_system_updates as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.config = {'inventories': ['dummy'], 'ansible_inventory': 'dummy', 'ansible_playbook': 'dummy',
                       'state_dir': '/tmp/state', 'policies': {},
                       'smtp': {'host': 'example.org', 'port': 587, 'username': 'user', 'password_file': '/private',
                                'sender': 'u@example.org', 'recipient': 'r@example.org'}}
        self.report = {'finished': u.now(), 'config_sha256': hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest(),
                       'hosts': [{'host': 'node', 'status': 'OK', 'operations': {'status': 'WARNING'}}]}
        self.policies = {'node': {'mode': 'security', 'restart_services': ['postfix.service'], 'health_ports': [25]}}

    def test_release_requires_fresh_matching_audit_and_successful_host(self):
        proposed = release.prepare(self.config, self.report, self.policies, 'node')
        self.assertEqual(proposed['canaries'], ['node'])
        self.assertEqual(self.config['policies'], {})
        for mutate in (
            lambda r: r.update(finished=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()),
            lambda r: r.update(config_sha256='changed'),
            lambda r: r['hosts'][0].update(status='FAILED'),
            lambda r: r['hosts'][0].update(operations={'status': 'CRITICAL'}),
        ):
            report = copy.deepcopy(self.report)
            mutate(report)
            with self.assertRaises(ValueError):
                release.prepare(self.config, report, self.policies, 'node')

    def test_invalid_health_ports_and_consumer_names_refused(self):
        for field, value in [('health_ports', [True]), ('health_ports', [0]),
                             ('restart_services', ['--help']), ('restart_podman_containers', ['bad/name'])]:
            policies = copy.deepcopy(self.policies)
            policies['node'][field] = value
            with self.assertRaises(ValueError):
                release.prepare(self.config, self.report, policies, 'node')

    def test_failed_live_preflight_does_not_release_policy_or_install_timer(self):
        with tempfile.TemporaryDirectory() as temp:
            config = copy.deepcopy(self.config)
            config['state_dir'] = temp
            report = copy.deepcopy(self.report)
            report['config_sha256'] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            paths = [Path(temp) / n for n in ('config.json', 'report.json', 'policies.json')]
            for path, value in zip(paths, (config, report, self.policies)):
                u.write_json(path, value)
            argv = ['release', '--config', str(paths[0]), '--report', str(paths[1]), '--policies', str(paths[2]), '--canary', 'node']
            with patch.object(sys, 'argv', argv), patch.object(release, 'load_hosts', return_value=['node']), patch.object(release, 'command', return_value=SimpleNamespace(returncode=0, stdout='')) as command, patch.object(release, 'run_host', return_value={'status': 'FAILED'}) as probe:
                with self.assertRaises(SystemExit):
                    release.main()
            self.assertFalse(probe.call_args.args[3])
            self.assertEqual(u.private_json(paths[0]), config)
            self.assertEqual(command.call_count, 2)

    def test_successful_preflight_installs_hourly_timer_and_requests_first_run(self):
        with tempfile.TemporaryDirectory() as temp:
            config = copy.deepcopy(self.config)
            config['state_dir'] = temp
            report = copy.deepcopy(self.report)
            report['config_sha256'] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            paths = [Path(temp) / n for n in ('config.json', 'report.json', 'policies.json')]
            for path, value in zip(paths, (config, report, self.policies)):
                u.write_json(path, value)
            argv = ['release', '--config', str(paths[0]), '--report', str(paths[1]), '--policies', str(paths[2]), '--canary', 'node']
            with patch.object(sys, 'argv', argv), patch.object(release, 'load_hosts', return_value=['node']), patch.object(release, 'command', return_value=SimpleNamespace(returncode=0, stdout='')) as command, patch.object(release, 'run_host', return_value={'status': 'OK', 'checks': 'PASSED'}):
                release.main()
            self.assertEqual(u.private_json(paths[0])['policies']['node']['mode'], 'security')
            variables = u.private_json(next(Path(temp).glob('release-preflight-*/scheduler.json')))
            self.assertEqual(variables['system_update_scheduler_calendar'], '*-*-* *:15:00 Europe/Berlin')
            self.assertTrue(variables['system_update_scheduler_run_now'])
            self.assertIn('release_controller', command.call_args.args[0])

    def test_released_cohort_runs_before_unrelated_audit_failure(self):
        config = {'canaries': ['canary'], 'policies': {'canary': {'mode': 'security'}, 'worker': {'mode': 'security'}}}
        calls = []
        def run(config, host, policy, apply, path):
            calls.append((host, apply))
            return {'status': 'FAILED' if host == 'audit-failure' else 'OK'}
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'run_host', side_effect=run):
            u.process_hosts(config, ['audit-failure', 'canary', 'worker'], Path(temp))
        self.assertEqual(calls, [('canary', True), ('worker', True), ('audit-failure', False)])

    def test_failed_canary_defers_all_other_installations(self):
        config = {'canaries': ['canary'], 'policies': {'canary': {'mode': 'security'}, 'worker': {'mode': 'security'}}}
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'run_host', side_effect=[{'status': 'FAILED'}, {'status': 'OK'}]) as run:
            reports = u.process_hosts(config, ['worker', 'canary'], Path(temp))
        self.assertFalse(run.call_args.args[3])
        self.assertIn('deferred', reports[1])

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'real Ansible required')
    def test_real_ansible_service_tcp_and_podman_preflight(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as server:
            directory = Path(temp)
            server.bind(('127.0.0.1', 0))
            server.listen(10)
            for name, body in [('systemctl', 'echo active'), ('podman', "echo '[{\"State\": {\"Running\": true}}]'")]:
                script = directory / name
                script.write_text('#!/bin/sh\n' + body + '\n')
                script.chmod(0o700)
            play = directory / 'play.json'
            play.write_text(json.dumps([{'hosts': 'all', 'gather_facts': False, 'vars': {
                'ansible_python_interpreter': sys.executable,
                'system_updates_restart_services': ['postfix.service'],
                'system_updates_health_ports': [server.getsockname()[1]],
                'system_updates_restart_podman_containers': ['open-webui'],
            }, 'environment': {'PATH': str(directory) + ':' + os.environ['PATH']}, 'tasks': [
                {'ansible.builtin.include_tasks': str(ROOT / 'ansible/roles/system_updates/tasks/verify-consumers.yml')}
            ]}]))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(play)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_transaction_timeout_blocks_installation_in_subsequent_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {'state_dir': temp, 'canaries': ['node'], 'policies': {'node': {'mode': 'security'}}}
            with patch.object(u, 'run_host', return_value={'status': 'FAILED', 'reason': 'TIMEOUT_REMOTE_STATE_UNKNOWN'}):
                u.process_hosts(config, ['node'], Path(temp))
            self.assertTrue((Path(temp) / 'installation-blocked.json').exists())
            with patch.object(u, 'run_host', return_value={'status': 'OK'}) as run:
                report = u.process_hosts(config, ['node'], Path(temp))
            self.assertFalse(run.call_args.args[3])
            self.assertIn('deferred', report[0])


if __name__ == '__main__':
    unittest.main()
