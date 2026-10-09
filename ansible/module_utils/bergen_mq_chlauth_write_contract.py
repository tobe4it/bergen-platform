"""Strict command allowlist for a deferred IBM MQ CHLAUTH live adapter.

Pure offline code: no SSH, Podman, MQSC execution or filesystem changes.
Matching the allowlist never proves exclusive ownership of MQ objects.
"""
from .bergen_mq_chlauth import ChlauthPlanError, make_plan, LAB
from .bergen_mq_chlauth_mqsc import require_success

OPERATIONS = ("add_deny", "define_receiver", "add_allow",
              "remove_allow", "delete_receiver", "remove_deny")


def canonical_plan():
    nodes = {
        side: {"qmgr": data["qmgr"], "host": data["host"], "port": 1414}
        for side, data in LAB.items()
    }
    return make_plan("BGT.A1B2C3D", nodes)


class ApprovedCommandContract:
    """Reject commands that deviate from the reviewed, exact fixture."""

    def __init__(self, plan):
        expected = canonical_plan()
        if not isinstance(plan, dict) or set(plan) != {"a", "b"}:
            raise ChlauthPlanError("Only the exact two-host fixture is allowed")
        for side in ("a", "b"):
            for field in ("qmgr", "receiver", "peer_ip", "peer_subject",
                          "peer_issuer", "mcauser", "apply_order", "cleanup",
                          "cases", "define_receiver"):
                if plan[side].get(field) != expected[side].get(field):
                    raise ChlauthPlanError("Fixture plan deviates from reviewed identity: " + field)
        self.plan = plan

    def classify(self, side, command):
        if side not in ("a", "b") or not isinstance(command, str):
            raise ChlauthPlanError("Unknown QMgr side or command type")
        spec = self.plan[side]
        commands = dict(zip(OPERATIONS[:3], spec["apply_order"]))
        commands.update(zip(OPERATIONS[3:], spec["cleanup"]))
        matches = [name for name, value in commands.items() if value == command]
        if len(matches) != 1:
            raise ChlauthPlanError("Unreviewed MQSC command; mutation forbidden")
        return matches[0]

    def require_write_result(self, side, command, rc, stdout):
        operation = self.classify(side, command)
        require_success(rc, stdout)
        return operation


class OfflineOnlyMutationAdapter:
    """Never allow a live mutation before ownership and journaling exist."""

    def __init__(self, contract):
        if not isinstance(contract, ApprovedCommandContract):
            raise TypeError("Reviewed command contract required")
        self.contract = contract

    def apply(self, side, command):
        self.contract.classify(side, command)
        raise ChlauthPlanError(
            "Live CHLAUTH mutation not implemented: ownership lock, "
            "atomic journal and independently verified cleanup required"
        )
