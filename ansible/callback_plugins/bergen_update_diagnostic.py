"""Emit bounded update failures without copying module output or secrets."""
import json
from ansible.plugins.callback import CallbackBase

PREFIX = 'BERGEN_UPDATE_DIAGNOSTIC='
SAFE_MESSAGES = {
    'PYTHON3_APT_REQUIRED', 'NO_TRUSTED_SECURITY_SUITE_IN_CACHE',
    'APT_HOLD_QUERY_FAILED', 'APT_PLAN_REFUSED',
    'APT_UPDATE_FAILED_PARTIAL_CHANGES_POSSIBLE', 'APT_TARGET_VERSION_NOT_REACHED',
}
STAGES = {
    'Read operating system facts',
    'Require supported backend and explicit restart and verification policy for writes',
    'Read installed versions before transaction', 'Check service health before any update',
    'Refresh APT metadata strictly', 'Select or apply trusted distribution security fixes',
    'Select or apply DNF security fixes',
    'Restart explicitly configured consumers after package change',
    'Verify application endpoints after transaction',
    'Read versions even after partial package failure', 'Check Debian reboot marker',
    'Discover standalone DNF restart checker', 'Check DNF reboot requirement',
    'Write controller result without raw logs or credentials',
    'Require runner scope and private result location',
}


def classify(data, unreachable=False):
    if data.get('_ansible_no_log') or data.get('censored'):
        return 'ERROR_DETAILS_REDACTED'
    message = data.get('msg', '')
    if isinstance(message, str) and message in SAFE_MESSAGES:
        return message
    if data.get('assertion') == 'ansible_facts.pkg_mgr == \'apt\' or system_updates_dnf_metadata_verified | bool':
        return 'DNF_SECURITY_METADATA_NOT_VERIFIED'
    nested = data.get('module_results', {})
    if isinstance(nested, dict):
        for child in list(nested.values())[:8]:
            if isinstance(child, dict):
                code = classify({k: v for k, v in child.items() if k != 'module_results'}, unreachable)
                if not code.startswith('UNCLASSIFIED_'):
                    return code
    # Inspect text in memory, but emit only one fixed category.
    text = '\n'.join(str(data.get(k, '')) for k in
                     ('msg', 'stderr', 'module_stderr', 'module_stdout', 'exception')).lower()[:32768]
    for needles, category in [
        (('host key verification failed', 'remote host identification has changed'), 'SSH_HOST_KEY_FAILED'),
        (('could not resolve hostname', 'name or service not known', 'temporary failure in name resolution'), 'HOST_RESOLUTION_FAILED'),
        (('permission denied (publickey', 'permission denied (password', 'authentication failed'), 'SSH_AUTHENTICATION_FAILED'),
        (('connection timed out', 'operation timed out'), 'CONNECTION_TIMEOUT'),
        (('no route to host', 'network is unreachable'), 'NETWORK_UNREACHABLE'),
        (('connection refused',), 'CONNECTION_REFUSED'),
        (('missing sudo password', 'a password is required', 'incorrect sudo password',
          'not in the sudoers', 'become password', 'sudo: not found',
          'sudo: a terminal is required', 'sudo: sorry, you must have a tty'), 'BECOME_FAILED'),
        (('python: not found', 'python3: not found', 'interpreter', 'python version',
          'requires a minimum of python', 'no module named'), 'PYTHON_ENVIRONMENT_FAILED'),
        (('401 unauthorized', '401  unauthorized', '403 forbidden'), 'REPOSITORY_AUTHENTICATION_FAILED'),
        (('certificate verify failed', 'certificate verification failed'), 'TLS_VERIFICATION_FAILED'),
        (('module result deserialization failed', 'no start of json char found'), 'MODULE_RESULT_INVALID'),
        (('permission denied',), 'PERMISSION_DENIED'),
        (('update_policy_incomplete_or_unsupported',), 'UPDATE_POLICY_INCOMPLETE_OR_UNSUPPORTED'),
    ]:
        if any(needle in text for needle in needles):
            return category
    return 'UNCLASSIFIED_CONNECTION_FAILURE' if unreachable else 'UNCLASSIFIED_TASK_FAILURE'


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'bergen_update_diagnostic'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def record(self, result, unreachable=False, ignored=False):
        name = result._task.get_name().split(' : ')[-1]
        event = {'host': result._host.get_name(),
                 'task': name if name in STAGES else 'UNKNOWN_TASK',
                 'code': classify(result._result, unreachable),
                 'kind': 'UNREACHABLE' if unreachable else 'FAILED', 'ignored': bool(ignored)}
        rc = result._result.get('rc')
        if type(rc) is int:
            event['rc'] = rc
        self.events.append(event)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self.record(result, ignored=ignore_errors)

    def v2_runner_on_unreachable(self, result):
        self.record(result, unreachable=True)

    def v2_playbook_on_stats(self, stats):
        self._display.display(PREFIX + json.dumps(self.events[:32], ensure_ascii=True))
