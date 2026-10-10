"""Fail-closed offline parser of exact receiver CURRENT CHSTATUS evidence.

No MQ connection or mutation. A parsed no-current-status response is a
point-in-time observation, NOT ownership proof or authorization to DELETE.
The caller must guarantee fresh, side-bound MQSC capture and must prevent
concurrent changes before any live cleanup can be considered.
"""

import re

from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_write_contract import ApprovedCommandContract

_CODES = re.compile(r"\bAMQ\d{4}[A-Z]\b")
_ECHO = re.compile(r"1\s*:\s*(.+)")
_VERSION = re.compile(r"5724-H72\s+\(C\)\s+Copyright IBM Corp\..*")


def _unknown_line_kind(line):
    """Classify without echoing full (potentially sensitive) MQSC output."""
    if line.startswith("5724-"):
        return "copyright-or-version"
    if line.startswith("Starting MQSC"):
        return "qmgr-header"
    if re.match(r"^[0-9]+\s*:", line):
        return "command-echo"
    diagnostic = re.match(r"^(AMQ[0-9]{4}[A-Z])\b", line)
    if diagnostic:
        return "diagnostic-" + diagnostic.group(1)
    if line.startswith(("One ", "No ", "All ")):
        return "summary"
    return "other"


def current_status_command(plan, side):
    """Return the only permitted, exactly scoped read-only status command."""
    contract = ApprovedCommandContract(plan)
    if side not in ("a", "b"):
        raise ChlauthPlanError("Unknown receiver side")
    receiver = contract.plan[side]["receiver"]
    return "DISPLAY CHSTATUS('%s') CURRENT" % receiver


def require_no_current_receiver_status(plan, side, command, rc, stdout):
    """Accept only an exact MQSC 'no CURRENT status' response.

    This does NOT prove the channel was never active, has no saved state,
    is owned by this run, or will remain inactive until a later deletion.
    """
    expected = current_status_command(plan, side)
    if command != expected:
        raise ChlauthPlanError("Unreviewed or unscoped CHSTATUS command")
    if type(rc) is not int or rc not in (0, 10) or not isinstance(stdout, str):
        raise ChlauthPlanError("Unusable CHSTATUS rc/output")

    spec = ApprovedCommandContract(plan).plan[side]
    expected_qmgr = "Starting MQSC for queue manager %s." % spec["qmgr"]
    valid_lines = {
        expected_qmgr,
        "AMQ8420I: Channel Status not found.",
        "One MQSC command read.",
        "No commands have a syntax error.",
        "One valid MQSC command could not be processed.",
    }
    seen = []
    echo_seen = 0
    for line_number, raw in enumerate(stdout.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if _VERSION.fullmatch(line):
            continue
        echo = _ECHO.fullmatch(line)
        if echo:
            if echo.group(1) != expected:
                raise ChlauthPlanError("CHSTATUS echo differs from requested command")
            echo_seen += 1
        elif line in valid_lines:
            seen.append(line)
        else:
            raise ChlauthPlanError(
                "Unexpected CHSTATUS output line at %d (class=%s; chars=%d)"
                % (line_number, _unknown_line_kind(line), len(line))
            )

    if echo_seen != 1 or any(seen.count(line) != 1 for line in valid_lines):
        raise ChlauthPlanError("CHSTATUS evidence incomplete or duplicated")
    if _CODES.findall(stdout) != ["AMQ8420I"]:
        raise ChlauthPlanError("Unexpected MQSC diagnostic code")
    return {
        "side": side,
        "qmgr_expected": spec["qmgr"],
        "receiver": spec["receiver"],
        "status_query": expected,
        "current_instances_reported": False,
        "read_only": True,
        "can_authorize_delete": False,
        "can_authorize_live_apply": False,
    }
