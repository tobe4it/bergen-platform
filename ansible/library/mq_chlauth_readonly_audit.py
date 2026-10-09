#!/usr/bin/python
"""Validate live collected IBM MQ CHLAUTH MQSC evidence, without any MQ access.

Called on localhost. The Ansible playbook gathers all six DISPLAY responses
from the two MQ hosts first. This module strictly maps those responses to the
read-only adapter; it does not spawn processes or write MQ objects.
"""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.bergen_mq_chlauth import LAB, make_plan
from ansible.module_utils.bergen_mq_chlauth_readonly import ReadOnlyChlauthAdapter


def main():
    module = AnsibleModule(
        argument_spec=dict(
            responses=dict(type="dict", required=True, no_log=True),
        ),
        supports_check_mode=True,
    )
    responses = module.params["responses"]
    commands = {
        "qmgr": "DISPLAY QMGR CHLAUTH CERTLABL",
        "receiver": "DISPLAY CHANNEL('{receiver}') ALL",
        "rules": "DISPLAY CHLAUTH(*) ALL",
    }
    expected_sides = {"a", "b"}
    if not isinstance(responses, dict) or set(responses) != expected_sides:
        module.fail_json(msg="Require exactly two MQ host evidence groups a/b")
    plan = make_plan(
        "AUDIT.A1B2C3D",
        {side: {"host": data["host"], "qmgr": data["qmgr"], "port": 1414}
         for side, data in LAB.items()},
    )
    collected = {}
    for side in ("a", "b"):
        expected = set(commands)
        evidence = responses[side]
        if not isinstance(evidence, dict) or set(evidence) != expected:
            module.fail_json(msg="Unexpected or incomplete DISPLAY command set on " + side)
        for key, result in evidence.items():
            if (not isinstance(result, dict)
                    or type(result.get("rc")) is not int
                    or not isinstance(result.get("stdout"), str)):
                module.fail_json(msg="Invalid MQSC rc/stdout evidence on " + side)
            command = commands[key].format(receiver=plan[side]["receiver"])
            collected[(side, command)] = (result["rc"], result["stdout"])

    def runner(side, command):
        key = (side, command)
        if key not in collected:
            raise ValueError("Unrecognized read-only command")
        return collected[key]

    adapter = ReadOnlyChlauthAdapter(runner)
    try:
        checks = {side: adapter.preflight(side, plan[side]) for side in ("a", "b")}
    except Exception as exc:
        module.fail_json(msg="Live CHLAUTH read-only parser refused evidence: " + str(exc))
    module.exit_json(
        changed=False,
        read_only=True,
        verification="PASS",
        qmgrs={side: checks[side]["qmgr"] for side in ("a", "b")},
        receivers={side: checks[side]["receiver"] for side in ("a", "b")},
        message="Both MQSC evidence sets passed strict read-only CHLAUTH preflight",
    )


if __name__ == "__main__":
    main()
