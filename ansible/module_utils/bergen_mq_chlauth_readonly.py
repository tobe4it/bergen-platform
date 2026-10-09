"""Read-only MQSC preflight adapter for exact CHLAUTH fixtures.

The caller supplies a function run(side, command) -> (rc, stdout), which is
restricted to MQSC DISPLAY by this adapter. No subprocess, SSH, REST or write
operation is implemented. This is deliberately NOT a lifecycle write adapter.

A successful inspection is a snapshot, not a lock or exclusive ownership
guarantee. A future mutating adapter must revalidate and solve that separately.
"""
import re

from .bergen_mq_chlauth import ChlauthPlanError, LAB
from .bergen_mq_audit_names import CHANNEL
from .bergen_mq_chlauth_mqsc import (
    require_success, channel_auth_records, exact_records,
)

_MISSING = re.compile(r"\b(?:AMQ8147E|AMQ8414E)\b")
_OTHER_ERRORS = re.compile(r"\bAMQ\d{4}E\b")
_VALID_CMD = re.compile(r"^DISPLAY (QMGR|CHANNEL|CHLAUTH)\b")


class ReadOnlyChlauthAdapter:
    """Take conservative snapshots; refuse any MQSC other than DISPLAY."""

    def __init__(self, run):
        if not callable(run):
            raise TypeError("A read-only MQSC runner callback is required")
        self._run = run

    def _display(self, side, command):
        if side not in LAB or not _VALID_CMD.match(command):
            raise ChlauthPlanError("Read-only MQSC DISPLAY commands only")
        if "\n" in command or "\r" in command:
            raise ChlauthPlanError("Exactly one MQSC DISPLAY command required")
        result = self._run(side, command)
        if (not isinstance(result, tuple) or len(result) != 2
                or type(result[0]) is not int or not isinstance(result[1], str)):
            raise ChlauthPlanError("MQSC runner must return (int rc, str output)")
        return result

    def preflight(self, side, spec):
        """Require exact receiver absence and no matching CHLAUTH records."""
        expected = LAB.get(side)
        if not expected or spec.get("qmgr") != expected["qmgr"]:
            raise ChlauthPlanError("Queue manager identity mismatch")
        receiver = spec.get("receiver")
        suffix = ".B2A" if side == "a" else ".A2B"
        if not isinstance(receiver, str) or not re.fullmatch(
                r"AUDIT\.[A-F0-9]{7}" + re.escape(suffix), receiver):
            raise ChlauthPlanError("Unsafe CHLAUTH receiver name")

        rc, qm = self._display(side, "DISPLAY QMGR CHLAUTH CERTLABL")
        require_success(rc, qm)
        if ("CHLAUTH(ENABLED)" not in qm
                or "CERTLABL(bergenlab)" not in qm
                or ("queue manager " + expected["qmgr"] + ".") not in qm):
            raise ChlauthPlanError("Queue manager CHLAUTH or certificate baseline drift")

        rc, channel = self._display(side, "DISPLAY CHANNEL('%s') ALL" % receiver)
        if (rc == 0 or not _MISSING.search(channel)
                or len(_MISSING.findall(channel)) != 1
                or len(_OTHER_ERRORS.findall(channel)) != 1
                or "No commands have a syntax error." not in channel
                or "One valid MQSC command could not be processed." not in channel):
            raise ChlauthPlanError("Receiver absence not proven unambiguously")

        rc, output = self._display(side, "DISPLAY CHLAUTH(*) ALL")
        records = channel_auth_records(rc, output)
        if exact_records(records, receiver):
            raise ChlauthPlanError("Existing fixture CHLAUTH records: collision")
        client = [r for r in records if r.get("CHLAUTH") == "BGT.CLIENT"]
        if (not any(r.get("TYPE") == "ADDRESSMAP"
                    and r.get("ADDRESS") == "*"
                    and r.get("USERSRC") == "NOACCESS" for r in client)
                or not any(r.get("TYPE") == "BLOCKUSER"
                           and r.get("USERLIST") == "*MQADMIN"
                           and r.get("CHLAUTH") == "*" for r in records)):
            raise ChlauthPlanError("Established client/admin CHLAUTH baseline drift")
        return {
            "qmgr": expected["qmgr"],
            "receiver": receiver,
            "receiver_absent": True,
            "exact_rules_absent": True,
            "client_rules_preserved": True,
            "chlauth_enabled": True,
        }

    def apply(self, side, statement):
        raise ChlauthPlanError("Read-only adapter: CHLAUTH mutation forbidden")

    def check(self, side, case):
        raise ChlauthPlanError("Read-only adapter: MATCH(RUNCHECK) requires a created receiver")

    def verify(self, side, spec, stage):
        raise ChlauthPlanError("Read-only adapter: lifecycle mutation verification unavailable")
