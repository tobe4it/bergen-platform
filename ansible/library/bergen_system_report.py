#!/usr/bin/python
"""Read-only operating report and central syslog aggregation; no package installs."""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.bergen_operations import collect_system, collect_logs, collect_logs_via_pct
import socket


def main():
    module = AnsibleModule(argument_spec={
        'mode': {'choices': ['system', 'syslog'], 'default': 'system'},
        'host_names': {'type': 'dict', 'default': {}},
        'since': {'type': 'float', 'default': 0},
        'until': {'type': 'float', 'default': 0},
        'via_ctid': {'type': 'int', 'default': 0},
        'expected_hostname': {'type': 'str', 'default': 'bergen-syslog'},
    }, supports_check_mode=True)
    try:
        if module.params['mode'] == 'system':
            result = collect_system()
        elif module.params['via_ctid']:
            if not 100 <= module.params['via_ctid'] <= 999999:
                module.fail_json(msg='INVALID_SYSLOG_CTID')
            result = collect_logs_via_pct(module.params['via_ctid'], module.params['expected_hostname'],
                                          module.params['host_names'], module.params['since'], module.params['until'])
        else:
            if socket.gethostname().split('.')[0] != module.params['expected_hostname']:
                module.fail_json(msg='CENTRAL_LOG_HOST_IDENTITY_MISMATCH')
            result = collect_logs(module.params['host_names'], module.params['since'], module.params['until'])
        module.exit_json(changed=False, operations=result)
    except Exception as exc:
        # Raw commands/logs/exception text never reach the report.
        module.fail_json(msg='OPERATIONS_PROBE_FAILED', error_type=type(exc).__name__)


if __name__ == '__main__':
    main()
