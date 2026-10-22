import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


u = load('system_updates', 'scripts/system_updates.py')
a = load('bergen_apt_security', 'ansible/library/bergen_apt_security.py')
f = load('update_filter', 'ansible/filter_plugins/system_update_report.py')


def version(number, origin='Debian', trusted=True, archive='trixie-security'):
    return NS(version=number, origins=[NS(origin=origin, trusted=trusted, archive=archive, codename=archive)])


def package(name, versions):
    return NS(name=name, is_installed=True, installed=NS(version='1'), versions=versions)


class SecuritySelectionTests(unittest.TestCase):
    def select(self, packages, held=()):
        return a.choose_versions(packages, set(held), ['Debian', 'Debian-Security'], 'trixie',
                                 lambda x, y: (int(x) > int(y)) - (int(x) < int(y)))

    def test_only_trusted_security_origin_and_same_release(self):
        packages = [package('php', [version('2'), version('3', archive='trixie-updates'),
                                   version('8', archive='forky-security'), version('9', trusted=False),
                                   version('10', origin='ThirdParty')])]
        selected, _ = self.select(packages)
        self.assertEqual(selected, [{'name': 'php', 'old': '1', 'new': '2'}])

    def test_held_security_update_is_visible_but_not_selected(self):
        selected, held = self.select([package('php', [version('2')])], ['php'])
        self.assertEqual(selected, [])
        self.assertEqual(held[0]['name'], 'php')

    def test_no_downgrade_and_best_security_version(self):
        selected, _ = self.select([package('php', [version('0'), version('2'), version('4')])])
        self.assertEqual(selected[0]['new'], '4')

    def test_version_delta_records_removal_and_addition(self):
        delta = f.package_delta({'old': [{'version': '1'}]}, {'new': [{'version': '2'}]})
        self.assertEqual([p['name'] for p in delta], ['new', 'old'])
        self.assertEqual(delta[1]['new'], [])


class RunnerTests(unittest.TestCase):
    def test_failure_stops_writes_but_all_hosts_are_reported(self):
        config = {'policies': {h: {'mode': 'security'} for h in ['a', 'b', 'c']}, 'canaries': ['a']}
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'run_host', side_effect=[
            {'status': 'FAILED'}, {'status': 'OK'}, {'status': 'OK'}]) as run:
            reports = u.process_hosts(config, ['c', 'b', 'a'], Path(temp))
        self.assertEqual([call.args[3] for call in run.call_args_list], [True, False, False])
        self.assertEqual(len(reports), 3)
        self.assertIn('deferred', reports[1])

    def test_exception_on_host_does_not_lose_remaining_hosts(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'run_host', side_effect=[
            OSError('password=SECRET'), {'status': 'OK'}]):
            reports = u.process_hosts({'policies': {}}, ['a', 'b'], Path(temp))
        self.assertEqual(len(reports), 2)
        self.assertNotIn('SECRET', json.dumps(reports))

    def test_audit_override_and_exclusion(self):
        config = {'policies': {'a': {'mode': 'security'}, 'b': {'mode': 'excluded', 'reason': 'maintenance'}}}
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'run_host', return_value={'status': 'OK'}) as run:
            reports = u.process_hosts(config, ['a', 'b'], Path(temp), True)
        self.assertFalse(run.call_args.args[3])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(reports[1]['status'], 'EXCLUDED')

    def test_inventory_includes_hosts_without_hostvars(self):
        data = {'_meta': {'hostvars': {'a': {}}}, 'workers': {'hosts': ['b', 'a']}}
        with patch.object(u, 'command', return_value=NS(returncode=0, stdout=json.dumps(data))):
            self.assertEqual(u.load_hosts({'inventories': ['dummy'], 'ansible_inventory': '/bin/true'}), ['a', 'b'])

    def test_missing_report_is_not_success_and_private_vars_removed(self):
        config = {'inventories': ['dummy'], 'ansible_playbook': 'ansible-playbook'}
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'command', return_value=NS(returncode=4)):
            result = u.run_host(config, 'a', {}, False, Path(temp) / 'result.json')
            self.assertEqual(result['status'], 'UNREACHABLE')
            self.assertFalse((Path(temp) / 'result.vars.json').exists())

    def test_report_html_escapes_inventory_text(self):
        report = {'run_id': 'test', 'started': '2026-10-22', 'finished': '2026-10-22',
                  'commit': 'abc', 'config_sha256': 'abc', 'mode': 'AUDIT',
                  'hosts': [{'host': '<script>', 'status': 'FAILED', 'reason': '<secret>'}]}
        _, plain, body = u.render(report)
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt;', body)
        self.assertIn('PRIORITÄT 1', plain)
        self.assertEqual(u.overall(report), 'FEHLER')

    def test_pending_audit_and_unknown_reboot_are_warnings(self):
        self.assertEqual(u.overall({'hosts': [{'status': 'OK', 'reboot': 'UNKNOWN'}]}), 'WARNUNG')
        self.assertEqual(u.overall({'hosts': [{'status': 'OK', 'mode': 'AUDIT', 'checks': 'PASSED',
                                             'reboot': 'NOT_REQUIRED', 'candidates': ['php']}]}), 'WARNUNG')

    def test_smtp_requires_starttls_before_login_and_attaches_only_report(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            secret = directory / 'password'
            secret.write_text('SECRET')
            secret.chmod(0o600)
            config = {'smtp': {'host': 'mail.example.org', 'port': 587, 'username': 'user',
                               'password_file': str(secret), 'sender': 'u@example.org', 'recipient': 'r@example.org'}}
            report = {'run_id': 'test', 'started': '2026-10-22', 'finished': '2026-10-22',
                      'commit': 'abc', 'config_sha256': 'abc', 'mode': 'AUDIT', 'hosts': []}
            with patch.object(u.smtplib, 'SMTP') as smtp:
                client = smtp.return_value.__enter__.return_value
                client.send_message.return_value = {}
                u.send_report(config, report, directory)
                names = [c[0] for c in client.method_calls]
                self.assertLess(names.index('starttls'), names.index('login'))
                self.assertLess(names.index('login'), names.index('send_message'))
                self.assertIsInstance(client.starttls.call_args.kwargs['context'], u.ssl.SSLContext)
            self.assertNotIn('SECRET', (directory / 'message.eml').read_text())
            self.assertEqual(json.loads((directory / 'delivery.json').read_text())['status'], 'SMTP_ACCEPTED')

    def test_no_smtp_login_if_starttls_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            secret = directory / 'password'
            secret.write_text('SECRET')
            secret.chmod(0o600)
            config = {'smtp': {'host': 'mail.example.org', 'port': 587, 'username': 'user', 'password_file': str(secret),
                               'sender': 'u@example.org', 'recipient': 'r@example.org'}}
            report = {'run_id': 't', 'started': 'x', 'finished': 'x', 'commit': 'x', 'config_sha256': 'x', 'mode': 'AUDIT', 'hosts': []}
            with patch.object(u.smtplib, 'SMTP') as smtp:
                client = smtp.return_value.__enter__.return_value
                client.starttls.side_effect = u.ssl.SSLError('bad certificate')
                with self.assertRaises(u.ssl.SSLError):
                    u.send_report(config, report, directory)
                client.login.assert_not_called()
                self.assertFalse((directory / 'delivery.json').exists())

    def test_watchdog_alerts_on_missing_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(u, 'command', return_value=NS(returncode=255)), patch.object(u, 'send_report') as send:
            rc = u.watchdog({'state_dir': temp, 'watchdog': {'ssh_target': 'ansible@controller', 'heartbeat_path': '/private/last-completed.json'}})
            self.assertEqual(rc, 1)
            self.assertIn('heartbeat', send.call_args.args[1]['error'])

    def test_watchdog_silent_for_recent_heartbeat(self):
        result = NS(returncode=0, stdout=json.dumps({'finished': u.now()}))
        with patch.object(u, 'command', return_value=result), patch.object(u, 'send_report') as send:
            rc = u.watchdog({'watchdog': {'ssh_target': 'ansible@controller', 'heartbeat_path': '/private/last-completed.json'}})
            self.assertEqual(rc, 0)
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
