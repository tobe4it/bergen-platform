#!/usr/bin/python
"""Ansible interface for the bounded Bergen MQ reconciler."""
DOCUMENTATION = r'''
---
module: mq_objects
short_description: Reconcile declared IBM MQ objects over authenticated HTTPS
description:
  - Uses JSON MQSC via mqweb; does not install MQ or connect over SSH.
  - Supports check mode and structured diffs. Not an IBM-supported module.
options:
  endpoint:
    description: HTTPS mqweb base URL ending in /ibmmq/rest/v2 or /v3.
    type: str
    required: true
  qmgr:
    description: Exact target queue manager name.
    type: str
    required: true
  username:
    description: REST administrative identity.
    type: str
    required: true
  password:
    description: REST password, supplied from Ansible Vault.
    type: str
    required: true
  ca_path:
    description: Optional CA bundle on the Ansible controller.
    type: path
  timeout:
    description: Request timeout in seconds; mutations are not retried.
    type: int
    default: 30
  allow_deletion:
    description: Explicitly authorize declared absent objects (never FORCE).
    type: bool
    default: false
  objects:
    description: Declarations with name, type, state and supported attributes.
    type: list
    elements: dict
    required: true
author:
  - Bergen Platform
'''
EXAMPLES = r'''
- name: Inspect declared MQ queue drift
  mq_objects:
    endpoint: "{{ mq_rest_endpoint }}"
    qmgr: "{{ mq_qmgr }}"
    username: "{{ mq_rest_username }}"
    password: "{{ vault_mq_rest_password }}"
    objects:
      - name: BERGEN.EVENTS
        type: qlocal
        attributes:
          maxdepth: 5000
          defpsist: "yes"
  check_mode: true
'''
RETURN = r'''
plans:
  description: Desired-state actions and before/after projections.
  type: list
  returned: success
applied:
  description: Mutations whose successful command responses were received.
  type: list
  returned: always
verified:
  description: Whether this was an apply run with post-change verification.
  type: bool
  returned: success
'''
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.bergen_mq import MQError, RestClient, reconcile, validate_objects


def main():
    module = AnsibleModule(argument_spec=dict(
        endpoint=dict(type="str", required=True), qmgr=dict(type="str", required=True),
        username=dict(type="str", required=True, no_log=True),
        password=dict(type="str", required=True, no_log=True), ca_path=dict(type="path"),
        timeout=dict(type="int", default=30), allow_deletion=dict(type="bool", default=False),
        objects=dict(type="list", elements="dict", required=True)), supports_check_mode=True)
    try:
        p = module.params
        validate_objects(p["objects"], p["allow_deletion"])
        client = RestClient(p["endpoint"], p["qmgr"], p["username"], p["password"], p["ca_path"], p["timeout"])
        result = reconcile(client, p["objects"], module.check_mode, p["allow_deletion"])
        if not module._diff:
            result.pop("diff")
        module.exit_json(**result)
    except MQError as exc:
        module.fail_json(msg=str(exc), changed=getattr(exc, "mutation_attempted", False),
                         applied=getattr(exc, "applied", []),
                         mutation_outcome_requires_review=getattr(exc, "mutation_attempted", False))
    except (ValueError, OSError):
        module.fail_json(msg="Invalid MQ REST/TLS configuration", changed=False)


if __name__ == "__main__":
    main()
