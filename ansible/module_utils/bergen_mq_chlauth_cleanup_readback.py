"""Pure offline receiver-cleanup evidence gate (read-only, never authorizes DELETE).

Before any hypothetical fixture receiver DELETE, the observed CHANNEL and
CHLAUTH records must match the exact reviewed fixture and show the allow rule
absent; an independently collected CURRENT CHSTATUS response must report no
current instance. This is a point-in-time format/contents check, NOT proof of
freshness, exclusive ownership, non-concurrent changes or permission to delete.

No process execution, MQ connection, filesystem changes or mutation API.
"""

from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_current_status import (
    current_status_command,
    require_no_current_receiver_status,
)
from .bergen_mq_chlauth_stage_readback import verify_stage_evidence
from .bergen_mq_chlauth_write_contract import ApprovedCommandContract


def verify_receiver_cleanup_readbacks(plan, side, responses):
    """Evaluate three caller-supplied DISPLAY responses; grant NO authority.

    responses:
      channel: {command, rc, stdout, stderr}  DISPLAY CHANNEL('<exact>') ALL
      rules:   {command, rc, stdout, stderr}  DISPLAY CHLAUTH(*) ALL
      current: {command, rc, stdout, stderr}  DISPLAY CHSTATUS('<exact>') CURRENT

    The caller remains responsible for independently collecting each response
    from the correct QM, its ordering, freshness and any concurrency control.
    """
    contract = ApprovedCommandContract(plan)
    if side not in ("a", "b"):
        raise ChlauthPlanError("Unknown queue manager side")

    spec = contract.plan[side]
    expected = {
        "channel": "DISPLAY CHANNEL('%s') ALL" % spec["receiver"],
        "rules": "DISPLAY CHLAUTH(*) ALL",
        "current": current_status_command(plan, side),
    }
    if not isinstance(responses, dict) or set(responses) != set(expected):
        raise ChlauthPlanError("Exactly three independent DISPLAY results required")

    checked = {}
    for kind, command in expected.items():
        row = responses[kind]
        if (not isinstance(row, dict)
                or set(row) != {"command", "rc", "stdout", "stderr"}
                or row["command"] != command
                or type(row["rc"]) is not int
                or not isinstance(row["stdout"], str)
                or not isinstance(row["stderr"], str)):
            raise ChlauthPlanError("Malformed or unscoped %s readback" % kind)
        if row["stderr"].strip():
            raise ChlauthPlanError("Unexpected %s readback stderr" % kind)
        checked[kind] = row

    # The receiver must still be defined with the reviewed TLS/MCAUSER
    # attributes, and the exact-profile SSLPEERMAP must ALREADY be absent,
    # while the fail-closed ADDRESSMAP deny remains.
    stage = verify_stage_evidence(
        plan, side, "no_allow",
        {
            kind: {"rc": checked[kind]["rc"], "stdout": checked[kind]["stdout"]}
            for kind in ("channel", "rules")
        },
    )
    current = checked["current"]
    status = require_no_current_receiver_status(
        plan, side, current["command"], current["rc"], current["stdout"]
    )
    if (stage["readback_contract"] != "PASS"
            or status["current_instances_reported"] is not False):
        raise ChlauthPlanError("Cleanup receiver readbacks not proven")

    return {
        "side": side,
        "qmgr_expected": spec["qmgr"],
        "receiver": spec["receiver"],
        "stage": "receiver_inactive",
        "readback_contract": "PASS",
        "allow_rule_absent_observed": True,
        "deny_rule_present_observed": True,
        "receiver_definition_present_observed": True,
        "no_current_status_observed": True,
        "read_only": True,
        "can_authorize_delete": False,
        "can_authorize_live_apply": False,
        "requires_independent_fresh_capture_and_exclusive_ownership": True,
    }
