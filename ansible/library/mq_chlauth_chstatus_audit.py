#!/usr/bin/python
"""Controller-only validation of confidential, collected CHSTATUS readbacks.

No SSH, Podman, runmqsc, mutation or subprocess usage in this module.
"""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.bergen_mq_chlauth_chstatus_audit import (
    audit_current_status,
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            responses=dict(type="dict", required=True, no_log=True),
        ),
        supports_check_mode=True,
    )
    try:
        result = audit_current_status(module.params["responses"])
    except Exception as exc:
        module.fail_json(
            changed=False,
            msg="Strict two-sided read-only CHSTATUS audit rejected evidence: " + str(exc),
        )
    module.exit_json(**result)


if __name__ == "__main__":
    main()
