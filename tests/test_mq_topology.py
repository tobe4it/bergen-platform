"""Offline orchestration/protocol safety tests, not live MQ acceptance."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_mq import mq, FakeClient
from test_mq_audit import audit

ROOT = Path(__file__).resolve().parents[1]
sys.modules['ansible.module_utils.bergen_mq'] = mq
sys.modules['ansible.module_utils.bergen_mq_audit'] = audit
spec_names = importlib.util.spec_from_file_location(
    'bergen_mq_audit_names', ROOT / 'ansible/module_utils/bergen_mq_audit_names.py')
audit_names_module = importlib.util.module_from_spec(spec_names)
sys.modules['ansible.module_utils.bergen_mq_audit_names'] = audit_names_module
spec_names.loader.exec_module(audit_names_module)
spec_transport = importlib.util.spec_from_file_location('bergen_mq_transport', ROOT / 'ansible/module_utils/bergen_mq_transport.py')
transport_module = importlib.util.module_from_spec(spec_transport)
sys.modules['ansible.module_utils.bergen_mq_transport'] = transport_module
spec_transport.loader.exec_module(transport_module)
spec = importlib.util.spec_from_file_location('topology', ROOT / 'ansible/module_utils/bergen_mq_topology.py')
topology = importlib.util.module_from_spec(spec)
spec.loader.exec_module(topology)


def nodes():
    return {s: dict(qmgr=q, endpoint='https://' + s + ':9443/ibmmq/rest/v3',
                    admin_user='admin', admin_password='hidden-admin', admin_ca='/tmp/ca',
                    host=s, port=1414, channel='BGT.CLIENT', username='mqtest',
                    password='hidden-client', ca='/tmp/ca', peer='CN=' + s,
                    protocol='TLSv1.3', cipher='TLS_AES_256_GCM_SHA384')
            for s, q in (('a', 'BERGENLAB'), ('b', 'BERGENLABB'))}


def success_probe(op, side='a', **kwargs):
    codes = dict(bad_password=2035, empty=2033, put_denied=2051, get_denied=2016, oversize=2030)
    return dict(ok=op not in codes and op != 'bad_trust', reason=codes.get(op, 0), tls_failure=op == 'bad_trust')


class TopologyTests(unittest.TestCase):
    def test_gates_before_connections_or_mutations(self):
        with self.assertRaises(ValueError):
            topology.run(nodes(), {'host': 'client'}, 'test', False)
        bad = nodes(); bad['b']['qmgr'] = 'PRODUCTION'
        with self.assertRaises(ValueError): topology.validate(bad, {'host': 'client'}, True)
        bad = nodes(); bad['a']['username'] = 'mqm'
        with self.assertRaises(ValueError): topology.validate(bad, {'host': 'client'}, True)

    def test_tls_12_and_non_tls_13_cipher_are_rejected(self):
        bad = nodes(); bad['a']['protocol'] = 'TLSv1.2'
        with self.assertRaisesRegex(ValueError, 'TLSv1.3'):
            topology.validate(bad, {'host': 'client'}, True)
        bad = nodes(); bad['a']['cipher'] = 'TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384'
        with self.assertRaisesRegex(ValueError, 'TLS 1.3 cipher'):
            topology.validate(bad, {'host': 'client'}, True)

    def test_working_subset_never_claims_full_pass(self):
        clients = dict(a=FakeClient(), b=FakeClient())
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, clients=clients, probe=success_probe)
        self.assertEqual(report['status'], 'PARTIAL', report['tests'])
        self.assertEqual(report['failed'], 0)
        self.assertGreaterEqual(report['passed'], 49)
        self.assertEqual(report['object_reports']['b']['qmgr'], 'BERGENLABB')
        self.assertTrue(all(not c.objects for c in clients.values()))
        self.assertNotIn('hidden-client', json.dumps(report))
        self.assertNotIn('hidden-admin', json.dumps(report))

    def test_run_scoped_local_queues_have_distinct_audit_aliases(self):
        clients = dict(a=FakeClient(), b=FakeClient())
        report = topology.run(
            nodes(), {'host': 'client'}, 'test', True,
            False, clients, success_probe,
        )
        prefix = report['prefix']
        self.assertRegex(prefix, r'^AUDIT\.[A-F0-9]{7}
        def probe(op, *args, **kwargs):
            if op == 'bad_password': return dict(ok=False, reason=2538, tls_failure=False)
            return success_probe(op, *args, **kwargs)
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, False,
                              dict(a=FakeClient(), b=FakeClient()), probe)
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(all(t['status'] == 'FAIL' for t in report['tests'] if t['id'].endswith(':invalid-password')))

    def test_timeout_retains_owned_fixtures_and_stops_mutations(self):
        def probe(op, *args, **kwargs):
            if op == 'roundtrip': raise mq.MQError('outcome uncertain')
            return success_probe(op, *args, **kwargs)
        clients = dict(a=FakeClient(), b=FakeClient())
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, False, clients, probe)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(len(report['residual_objects']), 2)  # physical LQ plus alias
        self.assertFalse(any(c[0] == 'delete' for c in clients['a'].calls))
        self.assertFalse(clients['b'].calls)

    def test_probe_overrides_payload_size_and_secrets_use_stdin_only(self):
        response = subprocess.CompletedProcess([], 0, '{"ok":true,"reason":0,"tls_failure":false}\n', '')
        with patch.object(topology.subprocess, 'run', return_value=response) as execute:
            result = topology.Probe(nodes(), {'host': 'client'})('roundtrip', size=4096)
        self.assertTrue(result['ok'])
        argv = execute.call_args.args[0]
        self.assertNotIn('hidden-client', str(argv))
        self.assertIn('StrictHostKeyChecking=yes', argv)
        properties = dict(line.split('=', 1) for line in execute.call_args.kwargs['input'].splitlines())
        self.assertEqual(base64.b64decode(properties['size']), b'4096')
        self.assertEqual(base64.b64decode(properties['a.password']), b'hidden-client')
        self.assertEqual(base64.b64decode(properties['a.protocol']), b'TLSv1.3')
        self.assertEqual(execute.call_args.kwargs['timeout'], 45)

    def test_malformed_probe_output_is_not_a_pass(self):
        for output in ('', '{}', '{"ok":"true","reason":0,"tls_failure":false}'):
            with patch.object(topology.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, 'secret')):
                with self.assertRaises(mq.MQError): topology.Probe(nodes(), {'host': 'client'})('connect')

    def test_cleanup_failure_survives_in_report(self):
        clients = dict(a=FakeClient(), b=FakeClient())
        original = clients['a'].command
        def command(cmd, *args, **kwargs):
            if cmd == 'delete': raise mq.MQError('in use')
            return original(cmd, *args, **kwargs)
        clients['a'].command = command
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, False, clients, success_probe)
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(report['residual_objects'])

    def test_java_compiles_and_selftest_uses_only_standard_runtime(self):
        import shutil
        import tempfile
        if not shutil.which('java'): self.skipTest('Java unavailable')
        with tempfile.TemporaryDirectory(prefix='bergen-probe-test-') as target:
            result = subprocess.run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-d', target,
                                     str(ROOT / 'tools/mq-tests/BergenMQProbe.java')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            values = {'operation': 'selftest', 'size': '4096', 'seed': '42'}
            payload = '\n'.join(k + '=' + base64.b64encode(v.encode()).decode() for k, v in values.items())
            run = subprocess.run(['java', '-cp', target, 'BergenMQProbe'], input=payload, capture_output=True, text=True)
            self.assertTrue(json.loads(run.stdout)['ok'])


if __name__ == '__main__': unittest.main()
)
        for side, client in clients.items():
            qlocals = {
                call[2]: call[3] for call in client.calls
                if call[0] == 'define' and call[1] == 'qlocal'
                and call[2].startswith('LQ.AUDIT.')
            }
            aliases = {
                call[2]: call[3] for call in client.calls
                if call[0] == 'define' and call[1] == 'qalias'
                and call[2].startswith('AUDIT.')
            }
            self.assertTrue(qlocals)
            self.assertEqual(len(qlocals), len(aliases))
            for alias, attrs in aliases.items():
                self.assertIn(attrs['target'], qlocals)
                self.assertEqual(alias, attrs['target'].removeprefix('LQ.'))
                self.assertLessEqual(len(alias), 48)
                self.assertLessEqual(len(attrs['target']), 48)
            self.assertFalse(client.objects)

    def test_negative_connection_does_not_accept_network_error(self):
        def probe(op, *args, **kwargs):
            if op == 'bad_password': return dict(ok=False, reason=2538, tls_failure=False)
            return success_probe(op, *args, **kwargs)
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, False,
                              dict(a=FakeClient(), b=FakeClient()), probe)
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(all(t['status'] == 'FAIL' for t in report['tests'] if t['id'].endswith(':invalid-password')))

    def test_timeout_retains_owned_fixtures_and_stops_mutations(self):
        def probe(op, *args, **kwargs):
            if op == 'roundtrip': raise mq.MQError('outcome uncertain')
            return success_probe(op, *args, **kwargs)
        clients = dict(a=FakeClient(), b=FakeClient())
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, False, clients, probe)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(len(report['residual_objects']), 1)
        self.assertFalse(any(c[0] == 'delete' for c in clients['a'].calls))
        self.assertFalse(clients['b'].calls)

    def test_probe_overrides_payload_size_and_secrets_use_stdin_only(self):
        response = subprocess.CompletedProcess([], 0, '{"ok":true,"reason":0,"tls_failure":false}\n', '')
        with patch.object(topology.subprocess, 'run', return_value=response) as execute:
            result = topology.Probe(nodes(), {'host': 'client'})('roundtrip', size=4096)
        self.assertTrue(result['ok'])
        argv = execute.call_args.args[0]
        self.assertNotIn('hidden-client', str(argv))
        self.assertIn('StrictHostKeyChecking=yes', argv)
        properties = dict(line.split('=', 1) for line in execute.call_args.kwargs['input'].splitlines())
        self.assertEqual(base64.b64decode(properties['size']), b'4096')
        self.assertEqual(base64.b64decode(properties['a.password']), b'hidden-client')
        self.assertEqual(base64.b64decode(properties['a.protocol']), b'TLSv1.3')
        self.assertEqual(execute.call_args.kwargs['timeout'], 45)

    def test_malformed_probe_output_is_not_a_pass(self):
        for output in ('', '{}', '{"ok":"true","reason":0,"tls_failure":false}'):
            with patch.object(topology.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, 'secret')):
                with self.assertRaises(mq.MQError): topology.Probe(nodes(), {'host': 'client'})('connect')

    def test_cleanup_failure_survives_in_report(self):
        clients = dict(a=FakeClient(), b=FakeClient())
        original = clients['a'].command
        def command(cmd, *args, **kwargs):
            if cmd == 'delete': raise mq.MQError('in use')
            return original(cmd, *args, **kwargs)
        clients['a'].command = command
        report = topology.run(nodes(), {'host': 'client'}, 'test', True, False, clients, success_probe)
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(report['residual_objects'])

    def test_java_compiles_and_selftest_uses_only_standard_runtime(self):
        import shutil
        import tempfile
        if not shutil.which('java'): self.skipTest('Java unavailable')
        with tempfile.TemporaryDirectory(prefix='bergen-probe-test-') as target:
            result = subprocess.run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-d', target,
                                     str(ROOT / 'tools/mq-tests/BergenMQProbe.java')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            values = {'operation': 'selftest', 'size': '4096', 'seed': '42'}
            payload = '\n'.join(k + '=' + base64.b64encode(v.encode()).decode() for k, v in values.items())
            run = subprocess.run(['java', '-cp', target, 'BergenMQProbe'], input=payload, capture_output=True, text=True)
            self.assertTrue(json.loads(run.stdout)['ok'])


if __name__ == '__main__': unittest.main()
