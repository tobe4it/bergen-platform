"""Pure, fail-closed audit of both collected CURRENT CHSTATUS responses.

Only validates supplied data; it has no MQ connectivity, no filesystem writes
and no authorization to delete, modify or create MQ objects. The Ansible
collector is responsible for fresh, per-host capture. Results are a snapshot,
not an exclusive lock or continuing proof of channel inactivity.
"""

from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_current_status import (
    current_status_command, require_no_current_receiver_status,
)
from .bergen_mq_chlauth_write_contract import canonical_plan


def audit_current_status(responses):
    """Validate full responses from exactly the two reviewed queue managers."""
    if not isinstance(responses, dict) or set(responses) != {"a", "b"}:
        raise ChlauthPlanError("Exactly two MQ CHSTATUS evidence sets required")
    plan = canonical_plan()
    checked = {}
    for side in ("a", "b"):
        result = responses[side]
        if not isinstance(result, dict) or set(result) != {"rc", "stdout", "stderr"}:
            raise ChlauthPlanError("Incomplete CHSTATUS response on " + side)
        if (type(result["rc"]) is not int
                or not isinstance(result["stdout"], str)
                or not isinstance(result["stderr"], str)):
            raise ChlauthPlanError("Invalid CHSTATUS rc/stdout/stderr on " + side)
        if result["stderr"].strip():
            raise ChlauthPlanError("Unexpected CHSTATUS stderr on " + side)

        command = current_status_command(plan, side)
        observation = require_no_current_receiver_status(
            plan, side, command, result["rc"], result["stdout"],
        )
        if observation["current_instances_reported"] is not False:
            raise ChlauthPlanError("No-current-status proof missing on " + side)
        checked[side] = {
            "qmgr": plan[side]["qmgr"],
            "receiver": plan[side]["receiver"],
            "no_current_status_observed": True,
        }

    return {
        "verification": "PASS",
        "read_only": True,
        "changed": False,
        "observations": checked,
        "can_authorize_delete": False,
        "can_authorize_live_apply": False,
        "message": (
            "Both real MQSC response sets match the strict no-CURRENT-status "
            "contract; this does not establish run ownership or deletion safety"
        ),
    }
