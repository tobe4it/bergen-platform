#!/usr/bin/python
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.bergen_mq_topology import run


def main():
    module = AnsibleModule(argument_spec=dict(
        nodes=dict(type='dict', required=True, no_log=True),
        ssh=dict(type='dict', required=True), revision=dict(type='str', required=True),
        confirm=dict(type='bool', default=False), include_objects=dict(type='bool', default=True),
        transient_transport=dict(type='bool', default=False),
        transport_peer_firewall_verified=dict(type='bool', default=False),
        transport_cross_ca_verified=dict(type='bool', default=False),
        transport_channel_security_verified=dict(type='bool', default=False)),
        supports_check_mode=False)
    try:
        report = run(**module.params)
    except Exception:
        module.fail_json(msg='Topology preflight failed; verify explicit consent, both lab identities and complete TLS/client settings', changed=False)
    module.exit_json(changed=True, report=report)


if __name__ == '__main__':
    main()
