"""Offline harness contracts, not real IBM MQ acceptance evidence."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_mq import mq, FakeClient

sys.modules['ansible.module_utils.bergen_mq'] = mq
spec = importlib.util.spec_from_file_location('audit', Path(__file__).resolve().parents[1] / 'ansible/module_utils/bergen_mq_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_consent_and_identity_reject_without_commands(self):
        for qmgr, consent in [('BERGENLAB', False), ('PRODUCTION', True)]:
            client = FakeClient()
            with self.assertRaises(mq.MQError):
                audit.run_audit(client, qmgr, 'test', consent)
            self.assertEqual(client.calls, [])

    def test_all_lifecycles_and_cleanup(self):
        client = FakeClient()
        report = audit.run_audit(client, 'BERGENLAB', 'test', True)
        self.assertEqual(report['status'], 'PASS', [t for t in report['tests'] if t['status'] != 'PASS'])
        self.assertGreater(report['passed'], 140)
        self.assertFalse(client.objects)
        self.assertEqual(len(report['cleanup']), 13)
        self.assertTrue(all(len(o['name']) <= 20 for o in audit.declarations(report['prefix']) if o['type'] == 'channel'))

    def test_failed_alter_still_cleans_up(self):
        client = FakeClient()
        original = client.command
        def command(cmd, *args, **kwargs):
            if cmd == 'alter':
                raise mq.MQError('Injected failure')
            return original(cmd, *args, **kwargs)
        client.command = command
        report = audit.run_audit(client, 'BERGENLAB', 'test', True)
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(client.objects)

    def test_unexpected_snapshot_failure_still_cleans_up(self):
        client = FakeClient()
        original = audit.discover
        counter = [0]
        def discover(*args):
            counter[0] += 1
            if counter[0] == 14:
                raise RuntimeError('secret must not escape')
            return original(*args)
        with patch.object(audit, 'discover', discover):
            report = audit.run_audit(client, 'BERGENLAB', 'test', True)
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(client.objects)
        self.assertNotIn('secret must not escape', str(report))

    def test_cleanup_failure_is_reported(self):
        client = FakeClient()
        original = client.command
        def command(cmd, *args, **kwargs):
            if cmd == 'delete':
                raise mq.MQError('Injected failure')
            return original(cmd, *args, **kwargs)
        client.command = command
        report = audit.run_audit(client, 'BERGENLAB', 'test', True)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(len(report['residual_objects']), 13)

    def test_targeted_namelist_sdr_linux_fixture_and_cleanup(self):
        client = FakeClient()
        report = audit.run_audit(client, 'BERGENLAB', 'test', True, 'namelist_sdr')
        self.assertEqual(report['status'], 'PASS')
        defines = [c for c in client.calls if c[0] == 'define']
        self.assertEqual([c[1] for c in defines], ['qlocal', 'namelist', 'channel'])
        self.assertEqual(defines[0][3]['usage'], 'xmitq')
        self.assertEqual(defines[2][3]['xmitq'], defines[0][2])
        self.assertNotIn('nltype', defines[1][3])
        self.assertIsInstance(defines[1][3]['names'], list)
        deletes = [c for c in client.calls if c[0] == 'delete']
        self.assertEqual(deletes[-1][2], defines[0][2])
        self.assertFalse(client.objects)
        self.assertEqual(report['scope'], 'namelist_sdr')


if __name__ == '__main__':
    unittest.main()
