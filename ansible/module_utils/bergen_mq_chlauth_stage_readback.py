"""Pure offline validation of per-stage MQSC DISPLAY evidence.

This is not a live execution adapter. Caller-supplied results may be stale,
replayed or fabricated; provenance, readback freshness, exclusive ownership,
QMGR baseline, and receiver inactivity require separate controls. In
particular, receiver_inactive is deliberately NOT supported here.
"""
import re

from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_mqsc import (
    channel_auth_records,
    require_exact_fixture_records,
    require_receiver_definition,
)
from .bergen_mq_chlauth_write_contract import ApprovedCommandContract

_PRESENT = frozenset(("receiver", "allow", "no_allow"))
_ABSENT = frozenset(("deny", "no_receiver", "clean"))
_MISSING = re.compile(r"\b(?:AMQ8147E|AMQ8414E)\b")
_ERRORS = re.compile(r"\bAMQ\d{4}E\b")


def _response(evidence, name):
    if not isinstance(evidence, dict) or set(evidence) != {"channel", "rules"}:
        raise ChlauthPlanError("Require exactly channel and rules readbacks")
    result = evidence[name]
    if (not isinstance(result, dict) or set(result) != {"rc", "stdout"}
            or type(result["rc"]) is not int
            or not isinstance(result["stdout"], str)):
        raise ChlauthPlanError("Unusable MQSC DISPLAY readback")
    return result["rc"], result["stdout"]


def _require_absent_channel(rc, output):
    """Require MQ's explicit object-not-found response, never silence."""
    if (rc == 0 or len(_MISSING.findall(output)) != 1
            or len(_ERRORS.findall(output)) != 1
            or output.count("One MQSC command read.") != 1
            or output.count("No commands have a syntax error.") != 1
            or output.count("One valid MQSC command could not be processed.") != 1):
        raise ChlauthPlanError("Receiver absence not independently evidenced")
    return True


def verify_stage_evidence(plan, side, stage, evidence):
    """Validate observed channel+CHLAUTH records for one exact fixture stage.

    Call with two fresh, separately executed MQSC DISPLAY responses; this
    function does not fetch them and cannot prove freshness or ownership.
    It cannot authorize deletion, CHSTATUS safety, or live writes.
    """
    # Do not allow arbitrary fixture identities, even in offline verification.
    contract = ApprovedCommandContract(plan)
    if side not in ("a", "b"):
        raise ChlauthPlanError("Unknown queue manager side")
    if stage not in _PRESENT | _ABSENT:
        raise ChlauthPlanError("Unsupported stage; inactivity requires CHSTATUS proof")
    spec = contract.plan[side]
    channel_rc, channel_output = _response(evidence, "channel")
    rules_rc, rules_output = _response(evidence, "rules")

    records = channel_auth_records(rules_rc, rules_output)
    require_exact_fixture_records(records, spec, stage)
    if stage in _PRESENT:
        require_receiver_definition(channel_rc, channel_output, spec)
    else:
        _require_absent_channel(channel_rc, channel_output)

    return {
        "side": side,
        "qmgr_expected": spec["qmgr"],
        "receiver": spec["receiver"],
        "stage": stage,
        "readback_contract": "PASS",
        "read_only": True,
        "can_authorize_live_apply": False,
        "can_authorize_delete": False,
    }
