"""Validated MQSC execution simulation; never contacts IBM MQ."""

from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_journal import LockedFixtureJournal
from .bergen_mq_chlauth_write_contract import ApprovedCommandContract


class InMemoryMqscRunner:
    """Supply predefined MQSC outcomes without executing commands."""

    def __init__(self, responses):
        if not isinstance(responses, dict):
            raise TypeError("Response mapping required")
        self.responses = dict(responses)
        self.calls = []

    def execute(self, side, command):
        self.calls.append((side, command))
        outcome = self.responses[(side, command)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class JournaledOfflineMqscExecutor:
    """Allowlist -> journal intent -> fake MQSC -> validate -> result."""

    def __init__(self, runner, journal, contract):
        if type(runner) is not InMemoryMqscRunner:
            raise ChlauthPlanError("Only in-memory MQSC runner allowed")
        if not isinstance(journal, LockedFixtureJournal):
            raise TypeError("Locked journal required")
        if not isinstance(contract, ApprovedCommandContract):
            raise TypeError("Approved command contract required")

        self.runner = runner
        self.journal = journal
        self.contract = contract
        self.blocked = False

    def apply(self, side, command):
        if self.blocked:
            raise ChlauthPlanError(
                "MQSC write state uncertain; manual recovery required"
            )

        operation = self.contract.classify(side, command)

        try:
            self.journal.intent(side, operation)
        except BaseException:
            self.blocked = True
            raise

        try:
            rc, stdout = self.runner.execute(side, command)
            self.contract.require_write_result(
                side, command, rc, stdout
            )
        except BaseException:
            self.blocked = True
            self.journal.result(side, operation, "UNKNOWN")
            raise

        try:
            self.journal.result(side, operation, "ACKED")
        except BaseException:
            self.blocked = True
            raise

        return operation
