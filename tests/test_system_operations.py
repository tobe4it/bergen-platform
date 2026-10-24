import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


helper = load('operations_helper', 'ansible/module_utils/bergen_operations.py')
ops = load('operations_script', 'scripts/system_operations.py')
runner = load('operations_runner', 'scripts/system_updates.py')


class OperationsTests(unittest.TestCase):
    def test_rpm_comparison_marks_older_running_kernel_and_refuses_unknown_runtime(self):
        package_text = '0\t5.14.0\t611.49.1.el9_7\tx86_64\n0\t5.14.0\t687.10.1.el9_8.0.1\tx86_64\n'
        comparison = Mock(side_effect=lambda a, b: (a > b) - (a < b))
        rpm = SimpleNamespace(labelCompare=comparison)
        uname = SimpleNamespace(release='5.14.0-611.49.1.el9_7.x86_64', machine='x86_64')
        with patch.dict(sys.modules, {'rpm': rpm}), patch.object(helper.os, 'uname', return_value=uname), patch.object(helper, 'bounded', side_effect=[
            {'status': 'FAILED', 'text': ''}, {'status': 'OK', 'text': package_text}
        ]):
            result = helper.kernel_summary()
        self.assertEqual(result['reboot'], 'REQUIRED')
        self.assertTrue(comparison.called)
        uname.release = 'unknown-custom-kernel'
        with patch.dict(sys.modules, {'rpm': rpm}), patch.object(helper.os, 'uname', return_value=uname), patch.object(helper, 'bounded', side_effect=[
            {'status': 'FAILED', 'text': ''}, {'status': 'OK', 'text': package_text}
        ]):
            result = helper.kernel_summary()
        self.assertNotIn('reboot', result)

    def test_operations_error_does_not_prevent_update_failure_email(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {'state_dir': temp, 'inventories': ['dummy'], 'ansible_inventory': 'dummy',
                      'policies': {}, 'operations': {'enabled': True}}
            adapter = SimpleNamespace(collect=Mock(side_effect=OSError('SECRET')))
            with patch.object(runner, 'validate'), patch.object(runner, 'command', side_effect=[
                SimpleNamespace(returncode=0, stdout='commit'), SimpleNamespace(returncode=0, stdout=''),
            ]), patch.object(runner, 'load_hosts', return_value=['host']), patch.object(runner, 'run_host', return_value={
                'status': 'FAILED', 'reason': 'TASK_FAILED'}), patch.object(runner, 'operations_module', return_value=adapter), patch.object(runner, 'send_report') as send:
                code = runner.run(config, True)
            self.assertEqual(code, 1)
            send.assert_called_once()
            report = send.call_args.args[1]
            self.assertEqual(report['operations_error'], 'OSError')
            self.assertNotIn('SECRET', json.dumps(report))

    def test_command_output_is_bounded_and_timeout_is_visible(self):
        result = helper.bounded([sys.executable, '-c', 'print("X" * 10000)'], limit=100)
        self.assertEqual(result['status'], 'TRUNCATED')
        self.assertEqual(len(result['text']), 100)
        result = helper.bounded([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=0.1)
        self.assertEqual(result['status'], 'TIMEOUT')

    def test_queue_and_wireguard_never_return_addresses_or_keys(self):
        queue = {'queue_id': 'ABC123', 'sender': 'private@example.invalid', 'recipients': ['SECRET']}
        with patch.object(helper, 'bounded', return_value={'status': 'OK', 'text': json.dumps(queue)}):
            result = helper.queue_summary()
        self.assertEqual(result['observed_messages'], 1)
        self.assertNotIn('private', json.dumps(result))
        dump = 'wg0\tSECRET_PRIVATE_KEY\tPUBLIC\t51820\toff\nwg0\tPEER\tSECRET_PSK\tPRIVATE_ENDPOINT\t10.0.0.0/8\t0\t1\t2\t25\n'
        with patch.object(helper, 'bounded', return_value={'status': 'OK', 'text': dump}):
            result = helper.wireguard_summary()
        self.assertEqual(result['peers'], 1)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('ENDPOINT', json.dumps(result))

    def test_central_logs_filter_time_and_host_and_omit_raw_content(self):
        now = dt.datetime(2026, 10, 24, 10, tzinfo=dt.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, '192.0.2.1.log').write_text(
                '2026-10-24T09:00:00+00:00 mx.example.invalid systemd: Failed to start dnf makecache SECRET\n'
                '2026-10-24T09:01:00+00:00 other.example.invalid postfix: status=deferred PRIVATE\n'
                '2026-10-20T09:01:00+00:00 mx.example.invalid postfix: status=deferred OLD\n'
                'Oct 24 09:01:00 mx.example.invalid oldformat SECRET\n')
            result = helper.collect_logs({'mx': ['mx.example.invalid'], 'missing': ['missing.invalid']},
                                          now - 86400, now, temp)
        self.assertEqual(result['hosts']['mx']['events'], {'DNF_CACHE_FAILED': 1})
        self.assertEqual(result['hosts']['missing']['status'], 'NO_RECENT_DATA')
        self.assertEqual(result['unparsed_records'], 1)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_duplicate_syslog_hostname_is_not_assigned_to_two_hosts(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'source.log').write_text('2026-10-24T09:00:00+00:00 shared systemd: Failed to start service\n')
            result = helper.collect_logs({'one': ['shared'], 'two': ['shared']}, 0, 9999999999, temp)
        self.assertTrue(all(h['status'] == 'AMBIGUOUS_HOSTNAME' for h in result['hosts'].values()))
        self.assertTrue(all(h['recent_records'] == 0 for h in result['hosts'].values()))

    def test_running_older_kernel_overrides_previous_no_reboot_evidence(self):
        report = {'hosts': [{'host': 'mx', 'status': 'FAILED', 'reboot': 'NOT_REQUIRED'}]}
        config = {'operations': {'enabled': True, 'syslog_host': 'collector'}}
        with tempfile.TemporaryDirectory() as temp, patch.object(ops, 'probe', side_effect=[
            {'status': 'WARNING', 'fqdn': 'mx.example.invalid', 'kernel': {'reboot': 'REQUIRED'}},
            {'status': 'OK', 'hosts': {'mx': {'status': 'NO_RECENT_DATA'}}}
        ]):
            ops.collect(config, report, Path(temp))
        self.assertEqual(report['hosts'][0]['reboot'], 'REQUIRED')
        self.assertIn('operations', report['hosts'][0])  # Collected despite update failure.
        self.assertIn('NO_RECENT_DATA', '\n'.join(ops.report_lines(report)))

    def test_operating_failure_and_missing_log_coverage_affect_email_status(self):
        host = {'host': 'one', 'status': 'OK', 'checks': 'PASSED', 'reboot': 'NOT_REQUIRED',
                'operations': {'status': 'CRITICAL'}}
        self.assertEqual(runner.overall({'hosts': [host]}), 'FEHLER')
        host['operations'] = {'status': 'OK', 'central_logs': {'status': 'NO_RECENT_DATA'}}
        self.assertEqual(runner.overall({'hosts': [host]}), 'WARNUNG')

    def test_syslog_guest_payload_works_without_ansible_and_checks_identity(self):
        captured = []
        def execute(argv, **kwargs):
            captured.append(argv)
            # Execute the real transported utility source on an empty temp log directory.
            with tempfile.TemporaryDirectory() as temp:
                args = json.loads(argv[-1])
                args['log_dir'] = temp
                result = subprocess.run([sys.executable, '-c', argv[-2], json.dumps(args)],
                                        capture_output=True, text=True, timeout=10)
            return {'status': 'OK' if result.returncode == 0 else 'FAILED', 'text': result.stdout}
        with patch.object(helper, 'bounded', side_effect=execute):
            result = helper.collect_logs_via_pct(120, helper.socket.gethostname().split('.')[0], {'mx': ['mx']}, 0, 1)
            self.assertEqual(result['hosts']['mx']['status'], 'NO_RECENT_DATA')
            refused = helper.collect_logs_via_pct(120, 'definitely-wrong-hostname', {}, 0, 1)
        self.assertEqual(refused['status'], 'ERROR')
        self.assertEqual(captured[0][:5], ['pct', 'exec', '120', '--', '/usr/bin/python3'])

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
    def test_real_ansible_can_package_operations_module_and_utility(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / 'play.yml'
            path.write_text(json.dumps([{'hosts': 'localhost', 'gather_facts': False,
                'vars': {'ansible_python_interpreter': sys.executable}, 'tasks': [
                    {'bergen_system_report': {'mode': 'system'}, 'register': 'op'},
                    {'ansible.builtin.assert': {'that': ['not op.changed', 'op.operations.status is defined',
                                                       'op.operations.postfix_queue.status is defined']}}
                ]}]))
            result = subprocess.run([shutil.which('ansible-playbook'), '-i', 'localhost,', '-c', 'local', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
    def test_runner_operations_play_writes_private_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            inventory = directory / 'inventory.json'
            inventory.write_text(json.dumps({'all': {'hosts': {'probe-host': {
                'ansible_connection': 'local', 'ansible_python_interpreter': sys.executable,
            }}}}))
            output = directory / 'operations.json'
            result = ops.probe({'ansible_playbook': shutil.which('ansible-playbook'),
                                'inventories': [str(inventory)]}, 'probe-host', {}, output)
            self.assertIn(result['status'], ('OK', 'WARNING', 'CRITICAL'))
            self.assertTrue(output.is_file())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertFalse(output.with_suffix('.vars.json').exists())

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
    def test_real_ansible_packaged_utility_transports_into_syslog_guest(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            logs = directory / 'logs'
            logs.mkdir()
            (logs / 'source.log').write_text('2026-10-24T09:00:00+00:00 mx.example.invalid systemd: Failed to start dnf makecache\n')
            fake_pct = directory / 'pct'
            fake_pct.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                + 'p=json.loads(sys.argv[-1]);p["log_dir"]=' + repr(str(logs)) + '\n'
                + 'sys.argv[-1]=json.dumps(p)\nos.execv(sys.executable,[sys.executable]+sys.argv[5:])\n')
            fake_pct.chmod(0o700)
            play = directory / 'play.yml'
            play.write_text(json.dumps([{'hosts': 'localhost', 'gather_facts': False,
                'vars': {'ansible_python_interpreter': sys.executable}, 'tasks': [
                    {'bergen_system_report': {'mode': 'syslog', 'via_ctid': 120,
                        'expected_hostname': helper.socket.gethostname().split('.')[0],
                        'host_names': {'mx': ['mx.example.invalid']}, 'since': 0, 'until': 9999999999}, 'register': 'op'},
                    {'ansible.builtin.assert': {'that': ['not op.changed', 'op.operations.hosts.mx.recent_records == 1',
                        'op.operations.hosts.mx.events.DNF_CACHE_FAILED == 1']}}
                ]}]))
            result = subprocess.run([shutil.which('ansible-playbook'), '-i', 'localhost,', '-c', 'local', str(play)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=60,
                                    env={**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH']})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
