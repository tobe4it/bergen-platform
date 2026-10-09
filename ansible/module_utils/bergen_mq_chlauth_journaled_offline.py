"""Offline-only integration of CHLAUTH lifecycle, allowlist and durable journal.

The delegate in this integration MUST be an in-memory fake. No actual MQSC
executor is connected or accepted: caller passes explicit offline_test=True,
and the wrapper rejects non-Fake objects by requiring a marker set on the
test harness class. This is test scaffolding, NOT a live-write adapter.
"""
from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_journal import LockedFixtureJournal
from .bergen_mq_chlauth_lifecycle import ChlauthFixtureLifecycle
from .bergen_mq_chlauth_write_contract import ApprovedCommandContract


class JournaledOfflineAdapter:
    """Write-ahead INTENT / RESULT wrapped around a simulated mutation."""

    def __init__(self, fake, journal, contract):
        if getattr(type(fake), "offline_chlauth_fake", False) is not True:
            raise ChlauthPlanError("Only explicit in-memory CHLAUTH fakes allowed")
        self.fake = fake
        self.journal = journal
        self.contract = contract

    def preflight(self, side, spec):
        return self.fake.preflight(side, spec)

    def verify(self, side, spec, stage):
        return self.fake.verify(side, spec, stage)

    def check(self, side, case):
        return self.fake.check(side, case)

    def apply(self, side, command):
        operation = self.contract.classify(side, command)
        self.journal.intent(side, operation)
        try:
            outcome = self.fake.apply(side, command)
        except BaseException:
            # Even an exception from a fake can represent a write that reached
            # MQ before the response was lost. Record UNKNOWN, not FAILED.
            self.journal.result(side, operation, "UNKNOWN")
            raise
        self.journal.result(side, operation, "ACKED")
        return outcome


def run_offline_journaled_fixture(plan, fake, directory):
    """Exercise lifecycle and journal against explicitly labeled fake only.

    A caught exception leaves an unfinished journal, blocking another run.
    CLEAN requires that both sides' post-cleanup verification succeeded.
    """
    if getattr(type(fake), "offline_chlauth_fake", False) is not True:
        raise ChlauthPlanError("No live MQSC runner may be passed here")
    contract = ApprovedCommandContract(plan)
    prefix = plan["a"]["receiver"].rsplit(".", 1)[0]
    with LockedFixtureJournal(directory, prefix) as journal:
        adapter = JournaledOfflineAdapter(fake, journal, contract)
        states = ChlauthFixtureLifecycle(plan, adapter).run()
        if not all(state.verified for state in states.values()):
            raise ChlauthPlanError("Independent two-sided cleanup not verified")
        journal.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
        return states, journal.path
