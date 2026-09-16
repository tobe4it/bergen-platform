"""Isolated single-QMgr acceptance tests; no channel starts or security changes."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from ansible.module_utils.bergen_mq import MQError, discover, reconcile, validate_objects


def now():
    return datetime.now(timezone.utc).isoformat()


class RecordedClient:
    def __init__(self, client):
        self.client, self.events = client, []

    def command(self, command, typ, name, parameters=None, response_parameters=None):
        event = dict(time=now(), command=command, type=typ, name=name,
                     parameters=deepcopy(parameters or {}))
        self.events.append(event)
        try:
            data = self.client.command(command, typ, name, parameters, response_parameters)
            event['completion'] = data.get('overallCompletionCode')
            event['reason'] = data.get('overallReasonCode')
            event['details'] = [{k: r.get(k) for k in ('completionCode', 'reasonCode')}
                                for r in data.get('commandResponse', [])]
            return data
        except MQError as exc:
            event['error'] = str(exc)
            raise


def declarations(prefix):
    result = []
    for suffix, typ, attrs in [
        ('QL', 'qlocal', dict(maxdepth=100, defpsist='yes', put='disabled')),
        ('QR', 'qremote', dict(rname=prefix + '.QL', rqmname='BGA.REMOTE', put='disabled')),
        ('QA', 'qalias', dict(target=prefix + '.QL', put='disabled')),
        ('QM', 'qmodel', dict(maxdepth=100, deftype='tempdyn')),
        ('TP', 'topic', dict(topicstr='bergen/audit/' + prefix, pub='disabled')),
        ('NL', 'namelist', dict(names=[prefix + '.QL'], nltype='queue')),
    ]:
        result.append(dict(name=prefix + '.' + suffix, type=typ,
                           attributes=dict(descr='Bergen isolated audit', **attrs)))
    for chltype in ('sdr', 'rcvr', 'svrconn', 'clntconn', 'clussdr', 'clusrcvr'):
        attrs = dict(descr='Bergen isolated audit', chltype=chltype)
        if chltype in ('sdr', 'clntconn', 'clussdr'):
            attrs['conname'] = '127.0.0.1(1)'
        result.append(dict(name=prefix + '.' + chltype.upper(), type='channel', attributes=attrs))
    return result


def run_audit(client, qmgr, revision, confirm=False):
    if not confirm or qmgr != 'BERGENLAB':
        raise MQError('Audit mutations require explicit evaluation consent and BERGENLAB')
    prefix = 'BGA.' + uuid.uuid4().hex[:7].upper()
    recorded = RecordedClient(client)
    report = dict(schema_version=1, started=now(), qmgr=qmgr, revision=revision,
                  prefix=prefix, evaluation_only=True, tests=[], cleanup=[],
                  commands=recorded.events, residual_objects=[],
                  limitations=[
                      'Functional evaluation, not independent audit or productive approval; clarify licensing with IBM.',
                      'Only declared test attributes are covered, not every allowlisted attribute/platform/version.',
                      'Cluster channels are definition tests only; no active cluster/multi-QMgr messaging is tested.',
                      'No CHLAUTH/OAM, subscriptions, QMGR attributes or services implementation exists.',
                      'Non-empty queue deletion/message PUT/GET, authorization-denied identity and TLS-negative live tests are not covered by this phase.',
                      'No reboot, backup/restore, upgrades, Syslog delivery or infrastructure security qualification.',
                      'This calls the same reconciliation engine through an Ansible audit module, not repeated CLI --check invocations.',
                  ])
    owned = []

    def case(name, operation, expected_error=None, mutation_free=False):
        start = len(recorded.events)
        item = dict(id=name, started=now(), status='FAIL')
        report['tests'].append(item)
        try:
            result = operation()
            if expected_error:
                raise AssertionError('Expected rejection did not occur')
            if result is not None:
                item['evidence'] = result
            item['status'] = 'PASS'
        except MQError as exc:
            item['error'] = str(exc)
            if expected_error and expected_error in str(exc):
                item['status'] = 'PASS'
        except AssertionError as exc:
            item['error'] = str(exc)
        except Exception:
            item['error'] = 'Unexpected test exception; details suppressed to protect credentials'
        item['command_range'] = [start, len(recorded.events)]
        if mutation_free and any(e['command'] != 'display' for e in recorded.events[start:]):
            item.update(status='FAIL', error='A read-only test attempted a mutation')
        item['finished'] = now()
        return item['status'] == 'PASS'

    def expect(result, changed, mutations):
        assert result['changed'] is changed, 'Unexpected changed flag'
        assert len(result['applied']) == mutations, 'Unexpected completed mutation count'
        return result

    objects = declarations(prefix)
    # Validate all declarations and reserve all names before any mutation.
    # A collision aborts without claiming ownership or deleting an existing object.
    objects = validate_objects(objects)
    for obj in objects:
        if discover(recorded, obj) is not None:
            raise MQError('Audit name collision: no existing object will be modified')
    for obj in objects:
        label = obj['type'] + ':' + obj['name']
        absent = dict(name=obj['name'], type=obj['type'], state='absent')
        if not case(label + ':check-create', lambda o=obj: expect(reconcile(recorded, [o], True), True, 0), mutation_free=True):
            continue
        # Record ownership before DEFINE so an uncertain response is handled by
        # targeted cleanup, never by blind retry or FORCE deletion.
        owned.append(absent)
        if not case(label + ':create', lambda o=obj: expect(reconcile(recorded, [o]), True, 1)):
            continue
        case(label + ':create-idempotent', lambda o=obj: expect(reconcile(recorded, [o]), False, 0), mutation_free=True)
        altered = dict(name=obj['name'], type=obj['type'], attributes=dict(descr='Bergen audit changed'))
        if obj['type'] == 'channel':
            altered['attributes']['chltype'] = obj['attributes']['chltype']
        def check_alter(o=altered, original=obj):
            result = expect(reconcile(recorded, [o], True), True, 0)
            delta = result['plans'][0]['parameters']
            assert set(delta) == ({'descr', 'chltype'} if original['type'] == 'channel' else {'descr'}), 'ALTER is not incremental'
            return result
        case(label + ':check-alter', check_alter, mutation_free=True)
        snapshot = {}
        def capture(o=obj):
            snapshot['before'] = discover(recorded, o)
        case(label + ':capture-before-alter', capture, mutation_free=True)
        case(label + ':alter', lambda o=altered: expect(reconcile(recorded, [o]), True, 1))
        case(label + ':alter-idempotent', lambda o=altered: expect(reconcile(recorded, [o]), False, 0), mutation_free=True)
        def preserved(original=obj, previous=snapshot.get('before')):
            after = discover(recorded, original)
            assert previous is not None and after is not None, 'Object missing during preservation check'
            for key in original['attributes']:
                if key != 'descr':
                    assert after.get(key) == previous.get(key), 'Unmanaged attribute changed: ' + key
            return dict(checked_attributes=[k for k in original['attributes'] if k != 'descr'])
        case(label + ':unmanaged-attributes-preserved', preserved, mutation_free=True)
        if obj['type'] == 'qlocal':
            conflict = dict(name=obj['name'], type='qremote', attributes={})
            case(label + ':queue-type-conflict', lambda: reconcile(recorded, [conflict]), 'queue type differs', True)
        if obj['type'] == 'channel':
            conflict = deepcopy(obj)
            conflict['attributes']['chltype'] = 'rcvr' if obj['attributes']['chltype'] != 'rcvr' else 'sdr'
            case(label + ':channel-type-conflict', lambda: reconcile(recorded, [conflict]), 'channel type differs', True)
        if obj['type'] == 'topic':
            conflict = deepcopy(obj)
            conflict['attributes']['topicstr'] += '/replacement'
            case(label + ':immutable-topicstr', lambda: reconcile(recorded, [conflict]), 'Changing topicstr', True)
        case(label + ':deletion-gate', lambda o=absent: reconcile(recorded, [o]), 'allow_deletion=true', True)
        case(label + ':check-delete', lambda o=absent: expect(reconcile(recorded, [o], True, True), True, 0), mutation_free=True)
        if case(label + ':delete-empty', lambda o=absent: expect(reconcile(recorded, [o], False, True), True, 1)):
            case(label + ':absent-idempotent', lambda o=absent: expect(reconcile(recorded, [o], False, True), False, 0), mutation_free=True)
    for label, payload, error in [
        ('protected-system-name', [dict(name='SYSTEM.BGA.TEST', type='qlocal')], 'system-owned'),
        ('wildcard-name', [dict(name=prefix + '.*', type='qlocal')], 'non-exact'),
        ('unknown-attribute', [dict(name=prefix + '.BAD', type='qlocal', attributes=dict(force='yes'))], 'Unsupported attribute'),
        ('invalid-enum', [dict(name=prefix + '.BAD', type='qlocal', attributes=dict(put='invalid'))], 'enum value'),
        ('duplicate-identity', [objects[0], objects[0]], 'Duplicate object identity'),
    ]:
        case(label, lambda p=payload: reconcile(recorded, p), error, True)
    # Best-effort cleanup limited to the reserved, uniquely generated identities.
    # The normal guarded reconciler refuses non-empty/in-use deletes; never FORCE.
    for obj in reversed(owned):
        start = len(recorded.events)
        entry = dict(name=obj['name'], type=obj['type'], status='FAIL')
        try:
            result = reconcile(recorded, [obj], allow_deletion=True)
            assert not reconcile(recorded, [obj], True, True)['changed'], 'Cleanup not verified'
            entry.update(status='PASS', mutations=len(result['applied']))
        except (MQError, AssertionError) as exc:
            entry['error'] = str(exc)
            report['residual_objects'].append(obj)
        except Exception:
            entry['error'] = 'Unexpected cleanup exception; manual inspection required'
            report['residual_objects'].append(obj)
        entry['command_range'] = [start, len(recorded.events)]
        report['cleanup'].append(entry)
    report['finished'] = now()
    report['passed'] = sum(t['status'] == 'PASS' for t in report['tests'])
    report['failed'] = sum(t['status'] == 'FAIL' for t in report['tests'])
    report['status'] = 'FAIL' if report['failed'] or report['residual_objects'] else 'PASS'
    return report
