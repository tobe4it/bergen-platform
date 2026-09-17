"""Bounded two-QMgr/client audit. No global security changes or service restarts."""
import base64
import json
import re
import shlex
import subprocess
import uuid
from datetime import datetime, timezone
from ansible.module_utils.bergen_mq import MQError, RestClient, discover, reconcile
from ansible.module_utils.bergen_mq_audit import run_audit


def now():
    return datetime.now(timezone.utc).isoformat()


LOCAL_CASES = ('roundtrip', 'nonpersistent', 'zero-length', 'binary-4k', 'alias', 'browse', 'correlation',
               'put_commit', 'put_rollback', 'disconnect_rollback', 'get_commit', 'get_rollback',
               'expiry', 'priority', 'fifo', 'empty', 'put_denied', 'get_denied', 'full', 'oversize')
TRANSPORT_CASES = ('persistent', 'nonpersistent', 'binary4k', 'commit', 'rollback')


DEFERRED = {
    'client-certificate-authentication': 'Needs dedicated client certificate, key and CHLAUTH certificate rules.',
    'channel-authentication-negative': 'Needs a separately scoped negative CHLAUTH fixture.',
    'channel-stop-backlog-recovery': 'Needs explicit disruption consent and exclusively owned SDR/XMITQ.',
    'qmgr-restart-persistence': 'Needs maintenance-window consent and persistent-message recovery checkpoints.',
    'qmgr-crash-recovery': 'Needs a separately authorized crash test and recoverable baseline.',
    'backup-restore': 'Needs backup storage, restore target and reviewed rollback procedure.',
    'dead-letter-routing-handler': 'Needs isolated DLQ/handler configuration without modifying the shared QMGR DLQ.',
    'pubsub-durable-retained': 'Needs subscription lifecycle harness and isolated topic authorization.',
    'cluster-routing': 'Needs separate reviewed repository/cluster configuration.',
    'ccdt-reconnect': 'Needs CCDT client harness; two independent QMgr are not replicas of one QMgr.',
    'xa-two-phase-commit': 'Needs an external transaction coordinator/resource manager.',
    'load-soak-concurrency': 'Needs agreed rate, duration and CPU/memory/disk safety limits.',
    'message-groups-segmentation-properties': 'Additional MQI/JMS test implementation required.',
    'request-reply-correlation': 'Additional cross-QMgr request/reply harness required.',
    'tls-rotation-revocation': 'Needs isolated certificate lifecycle fixtures and rollback.',
    'monitoring-syslog-delivery': 'Needs read access to the receiving monitoring/log service.',
    'upgrade-downgrade': 'Needs backup, compatibility assessment and separate approval.',
}


def validate(nodes, ssh, confirm):
    if not confirm or set(nodes) != {'a', 'b'}:
        raise ValueError('Explicit consent and exactly nodes a/b required')
    if nodes['a'].get('qmgr') != 'BERGENLAB' or nodes['b'].get('qmgr') != 'BERGENLABB':
        raise ValueError('Only the two evaluation QMgr identities are allowed')
    if nodes['a'].get('endpoint') == nodes['b'].get('endpoint'):
        raise ValueError('Distinct REST endpoints required')
    for node in nodes.values():
        for key in ('endpoint', 'admin_user', 'admin_password', 'admin_ca', 'host', 'channel', 'username', 'password', 'ca', 'peer', 'protocol', 'cipher'):
            if not isinstance(node.get(key), str) or not node[key] or 'CHANGE_ME' in node[key]:
                raise ValueError('Complete REST, TLS and dedicated client identity settings required')
        if node['protocol'] != 'TLSv1.3':
            raise ValueError('Topology audit requires TLSv1.3; TLSv1.2 is not accepted')
        if not node['cipher'].startswith('TLS_AES_'):
            raise ValueError('Topology audit requires a TLS 1.3 cipher suite')
        if not re.fullmatch(r'BGT\.[A-Z0-9.]{1,16}', node['channel']):
            raise ValueError('Dedicated BGT.* client channel required')
        if not 1 <= int(node.get('port', 1414)) <= 65535:
            raise ValueError('Invalid MQ port')
        if node['username'].lower() in {'root', 'mqm', 'admin'}:
            raise ValueError('Client tests must use a non-administrator identity')
        if node.get('denied_queue') and not re.fullmatch(r'BGT\.DENIED[A-Z0-9.]*', node['denied_queue']):
            raise ValueError('OAM negative fixture must be a dedicated BGT.DENIED* queue')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', ssh.get('host', '')):
        raise ValueError('Exact client SSH hostname/IP required')
    if not 1 <= int(ssh.get('port', 22)) <= 65535:
        raise ValueError('Invalid SSH port')


class Probe:
    def __init__(self, nodes, ssh):
        self.nodes, self.ssh = nodes, ssh

    def __call__(self, operation, side='a', **settings):
        properties = dict(operation=operation, side=side, size=128,
                          persistence=1, seed=uuid.uuid4().int % (2**63))
        properties.update(settings)
        for label, node in self.nodes.items():
            for key in ('host', 'port', 'qmgr', 'channel', 'username', 'password', 'ca', 'peer', 'protocol', 'cipher'):
                properties[label + '.' + key] = node.get(key, 1414 if key == 'port' else '')
        # Stdin only; no secrets in process argv, command output or evidence.
        payload = '\n'.join(k + '=' + base64.b64encode(str(v).encode()).decode() for k, v in properties.items())
        remote = ['/usr/sbin/runuser', '-u', 'mqtest', '--', '/usr/bin/java',
                  '-Dcom.ibm.mq.cfg.useIBMCipherMappings=false', '-cp',
                  '/opt/bergen-mq-client/tests:/opt/bergen-mq-client/lib/com.ibm.mq.allclient.jar', 'BergenMQProbe']
        argv = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=10', '-p', str(self.ssh.get('port', 22)),
                'root@' + self.ssh['host'], shlex.join(remote)]
        try:
            result = subprocess.run(argv, input=payload, text=True, capture_output=True, timeout=45, check=False)
            if result.returncode != 0 or len(result.stdout) > 16384:
                raise MQError('Client process or SSH failed; details suppressed')
            data = json.loads(result.stdout.strip().splitlines()[-1])
            if (not isinstance(data, dict) or type(data.get('ok')) is not bool
                    or type(data.get('reason')) is not int or type(data.get('tls_failure')) is not bool):
                raise ValueError('Invalid probe protocol')
            return {k: data[k] for k in ('ok', 'reason', 'tls_failure')}
        except subprocess.TimeoutExpired:
            # A remote child may still be running: leave fixtures for review.
            raise MQError('Client timeout; remote outcome uncertain, retain fixtures') from None
        except (OSError, ValueError, IndexError):
            raise MQError('Client execution/protocol failed; details suppressed') from None


def summarize(report):
    observed = {t['id'] for t in report['tests']}
    for name in report['planned']:
        if name not in observed:
            report['tests'].append(dict(id=name, status='NOT_TESTED', detail='Prerequisite failed or execution stopped; no result inferred'))
    report['passed'] = sum(t['status'] == 'PASS' for t in report['tests'])
    report['failed'] = sum(t['status'] == 'FAIL' for t in report['tests'])
    report['not_tested'] = sum(t['status'] == 'NOT_TESTED' for t in report['tests'])
    report['status'] = ('FAIL' if report['failed'] or report['residual_objects'] else
                        'PARTIAL' if report['not_tested'] else 'PASS')
    report['finished'] = now()
    return report


def run(nodes, ssh, revision, confirm=False, include_objects=True, clients=None, probe=None):
    validate(nodes, ssh, confirm)
    prefix = 'BGT.' + uuid.uuid4().hex[:7].upper()
    report = dict(schema_version=1, prefix=prefix, revision=revision, started=now(),
                  evaluation_only=True, tests=[], cleanup=[], residual_objects=[], object_reports={},
                  targets={s: {k: n.get(k) for k in ('qmgr', 'host', 'port', 'channel', 'protocol', 'cipher')} for s, n in nodes.items()},
                  limitations=['Not an independent audit or production approval.',
                               'No claim to all possible MQ product configurations; deferred cases remain NOT_TESTED.',
                               'Infrastructure/backup/HA availability is not established by two independent QMgr.'])
    report['planned'] = ['client:api-preflight'] + list(DEFERRED)
    for side in ('a', 'b'):
        report['planned'] += [side + ':' + c for c in ('tls-authenticated-connect', 'object-lifecycle',
            'invalid-password', 'untrusted-certificate', 'valid-credentials-after-negatives', 'oam-denied') + LOCAL_CASES]
        report['planned'] += [side + ':remote-' + c for c in TRANSPORT_CASES]
    for name, reason in DEFERRED.items():
        report['tests'].append(dict(id=name, status='NOT_TESTED', detail=reason))
    owned, uncertain = [], False
    clients = clients or {s: RestClient(n['endpoint'], n['qmgr'], n['admin_user'], n['admin_password'], n['admin_ca']) for s, n in nodes.items()}
    probe = probe or Probe(nodes, ssh)

    def case(name, operation, expected=0, tls=False):
        nonlocal uncertain
        row = dict(id=name, status='FAIL', started=now())
        report['tests'].append(row)
        try:
            evidence = operation()
            if evidence is not None:
                row['evidence'] = evidence
                if expected:
                    assert not evidence['ok'] and evidence['reason'] == expected, 'Expected MQ reason not observed'
                elif tls:
                    assert not evidence['ok'] and evidence['tls_failure'], 'Expected TLS-specific rejection not observed'
                else:
                    assert evidence['ok'], 'Probe did not pass'
            row['status'] = 'PASS'
        except Exception as exc:
            # Never copy unknown exception strings, response bodies or credentials.
            row['detail'] = 'Case failed; check bounded MQ reason evidence and residual objects.'
            if isinstance(exc, MQError) and 'outcome uncertain' in str(exc):
                uncertain = True
                row['detail'] = 'Timeout: remote client outcome uncertain; stop further mutations and retain fixtures.'
        row['finished'] = now()
        return row['status'] == 'PASS'

    def fixture(side, name, typ='qlocal', **attrs):
        obj = dict(name=name, type=typ, state='present', attributes=attrs)
        if discover(clients[side], obj) is not None:
            raise MQError('Name collision; no ownership acquired')
        owned.append((side, dict(name=name, type=typ, state='absent')))
        reconcile(clients[side], [obj])

    ready = {}
    try:
        if not case('client:api-preflight', lambda: probe('api')):
            return summarize(report)
        for side in ('a', 'b'):
            if uncertain:
                report['tests'].append(dict(id=side + ':remaining-cases', status='NOT_TESTED', detail='Remote process outcome uncertain'))
                break
            ready[side] = case(side + ':tls-authenticated-connect', lambda s=side: probe('connect', s))
            if include_objects:
                def object_audit(s=side):
                    result = run_audit(clients[s], nodes[s]['qmgr'], revision, True)
                    report['object_reports'][s] = result
                    assert result['status'] == 'PASS'
                case(side + ':object-lifecycle', object_audit)
            else:
                report['tests'].append(dict(id=side + ':object-lifecycle', status='NOT_TESTED', detail='Disabled by caller'))
            if not ready[side]:
                report['tests'].append(dict(id=side + ':messaging', status='NOT_TESTED', detail='Positive TLS/authentication prerequisite failed'))
                continue
            case(side + ':invalid-password', lambda s=side: probe('bad_password', s), expected=2035)
            case(side + ':untrusted-certificate', lambda s=side: probe('bad_trust', s), tls=True)
            case(side + ':valid-credentials-after-negatives', lambda s=side: probe('connect', s))
            for index, op in enumerate(LOCAL_CASES):
                if uncertain:
                    break
                name = prefix + '.' + side.upper() + str(index)
                def execute(s=side, q=name, operation=op):
                    attrs = dict(maxdepth=1 if operation == 'full' else 10, maxmsgl=4096, defpsist='yes')
                    if operation == 'put_denied': attrs['put'] = 'disabled'
                    if operation == 'get_denied': attrs['get'] = 'disabled'
                    fixture(s, q, **attrs)
                    settings = dict(queue=q)
                    action = operation
                    if operation in ('nonpersistent', 'zero-length', 'binary-4k'):
                        action = 'roundtrip'
                        settings.update(size=0 if operation == 'zero-length' else 4096 if operation == 'binary-4k' else 128,
                                        persistence=0 if operation == 'nonpersistent' else 1)
                    if operation == 'oversize': settings['size'] = 4097
                    if operation == 'alias':
                        fixture(s, q + '.AL', 'qalias', target=q)
                        settings.update(queue=q + '.AL', other_queue=q)
                    return probe(action, s, **settings)
                expected = {'empty': 2033, 'put_denied': 2051, 'get_denied': 2016, 'oversize': 2030}.get(op, 0)
                case(side + ':' + op, execute, expected=expected)
            denied = nodes[side].get('denied_queue', '')
            if denied and not uncertain:
                def no_authority(s=side, q=denied):
                    assert discover(clients[s], dict(name=q, type='qlocal', state='present', attributes={})) is not None
                    return probe('put_denied', s, queue=q)
                case(side + ':oam-denied', no_authority, expected=2035)
            else:
                report['tests'].append(dict(id=side + ':oam-denied', status='NOT_TESTED', detail='Needs an existing denied queue fixture'))
        for side, dest in (('a', 'b'), ('b', 'a')):
            channel, xmitq = nodes[side].get('sender_channel', ''), nodes[side].get('xmitq', '')
            if uncertain or not all(ready.values()) or not channel or not xmitq:
                report['tests'].append(dict(id=side + ':remote-transport', status='NOT_TESTED', detail='Needs both positive connections and dedicated TLS SDR/RCVR/XMITQ fixtures'))
                continue
            def transport(s=side, d=dest, ch=channel, xq=xmitq, variant='persistent'):
                assert re.fullmatch(r'BGT\.[A-Z0-9.]{1,16}', ch)
                assert re.fullmatch(r'BGT\.[A-Z0-9.]{1,44}', xq)
                sender = discover(clients[s], dict(name=ch, type='channel', state='present', attributes={'chltype': 'sdr'}))
                receiver = discover(clients[d], dict(name=ch, type='channel', state='present', attributes={'chltype': 'rcvr'}))
                assert sender and receiver and sender.get('sslciph') and receiver.get('sslciph')
                assert sender.get('xmitq') == xq
                suffix = variant.upper()
                q = prefix + '.' + d.upper() + '.' + suffix + '.IN'
                remote = prefix + '.' + s.upper() + '.' + suffix + '.REMOTE'
                fixture(d, q, maxdepth=10, maxmsgl=4096, defpsist='yes')
                fixture(s, remote, 'qremote', rname=q, rqmname=nodes[d]['qmgr'], xmitq=xq)
                result = probe('route_' + variant if variant in ('commit', 'rollback') else 'route', s,
                               queue=remote, other_queue=q, destination=d,
                               persistence=0 if variant == 'nonpersistent' else 1,
                               size=4096 if variant == 'binary4k' else 128)
                return result
            for variant in TRANSPORT_CASES:
                if uncertain:
                    break
                case(side + ':remote-' + variant, lambda v=variant: transport(variant=v))
    except Exception:
        report['tests'].append(dict(id='orchestration', status='FAIL', detail='Unexpected orchestration failure; details suppressed'))
    finally:
        for side, obj in reversed(owned):
            entry = dict(side=side, **obj, status='FAIL')
            try:
                if uncertain:
                    raise MQError('Uncertain remote process; retain fixture')
                reconcile(clients[side], [obj], allow_deletion=True)
                assert not reconcile(clients[side], [obj], True, True)['changed']
                entry['status'] = 'PASS'
            except Exception:
                entry['detail'] = 'Retained for review; no FORCE, CLEAR or drain was attempted'
                report['residual_objects'].append(dict(side=side, **obj))
            report['cleanup'].append(entry)
    return summarize(report)
