#!/usr/bin/python
"""Run isolated functional audit cases on the explicitly authorized lab QMGR."""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.bergen_mq import RestClient, MQError
from ansible.module_utils.bergen_mq_audit import run_audit


def main():
    module = AnsibleModule(argument_spec=dict(
        endpoint=dict(type='str', required=True), qmgr=dict(type='str', required=True),
        username=dict(type='str', required=True, no_log=True),
        password=dict(type='str', required=True, no_log=True),
        ca_path=dict(type='path', required=True), revision=dict(type='str', required=True),
        confirm=dict(type='bool', default=False)), supports_check_mode=False)
    p = module.params
    try:
        client = RestClient(p['endpoint'], p['qmgr'], p['username'], p['password'], p['ca_path'])
        report = run_audit(client, p['qmgr'], p['revision'], p['confirm'])
        module.exit_json(changed=any(e['command'] != 'display' for e in report['commands']), report=report)
    except (MQError, OSError, ValueError):
        module.fail_json(msg='Audit preflight failed before test mutations; verify consent, lab identity, names and HTTPS access', changed=False)


if __name__ == '__main__':
    main()
