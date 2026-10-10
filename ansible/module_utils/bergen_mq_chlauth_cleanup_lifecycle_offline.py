"""Offline-only bridge: lifecycle -> journaled fake -> cleanup readback gate.

This adapter deliberately accepts only JournaledOfflineAdapter (which itself
requires an explicitly marked in-memory fake). It cannot reach MQ. The
readback callback supplies simulated data; it is not a provenance/freshness or
ownership proof, and neither this class nor its output authorizes a live DELETE.
"""
from .bergen_mq_chlauth import ChlauthPlanError
from .bergen_mq_chlauth_cleanup_readback import verify_receiver_cleanup_readbacks
from .bergen_mq_chlauth_journaled_offline import JournaledOfflineAdapter
from .bergen_mq_chlauth_write_contract import ApprovedCommandContract


class OfflineReadbackGatedLifecycleAdapter:
    """Ensure an offline receiver delete follows all three readback checks."""

    def __init__(self, plan, journaled_fake_adapter, readback_provider):
        contract = ApprovedCommandContract(plan)
        if type(journaled_fake_adapter) is not JournaledOfflineAdapter:
            raise ChlauthPlanError("Journaled in-memory fake adapter required")
        if journaled_fake_adapter.contract.plan != contract.plan:
            raise ChlauthPlanError("Journaled fixture plan mismatch")
        if not callable(readback_provider):
            raise TypeError("Offline readback callback required")
        self.plan = contract.plan
        self.delegate = journaled_fake_adapter
        self.readback_provider = readback_provider
        self._no_allow_verified = set()
        self._inactive_verified = set()
        self._no_receiver_verified = set()
        self._delete_completed = set()

    def preflight(self, side, spec):
        return self.delegate.preflight(side, spec)

    def check(self, side, case):
        return self.delegate.check(side, case)

    def verify(self, side, spec, stage):
        if side not in ("a", "b") or spec != self.plan[side]:
            raise ChlauthPlanError("Unexpected readback side or fixture")
        if stage == "receiver_inactive":
            if side not in self._no_allow_verified:
                raise ChlauthPlanError(
                    "Refuse offline receiver deletion without verified no_allow"
                )
            # Existing lifecycle fake may still inject a verification fault.
            self.delegate.verify(side, spec, stage)
            verify_receiver_cleanup_readbacks(
                self.plan, side, self.readback_provider(side)
            )
            self._inactive_verified.add(side)
            return True
        if stage == "no_receiver" and side not in self._delete_completed:
            raise ChlauthPlanError(
                "Receiver absence stage refused before a completed fake delete"
            )
        outcome = self.delegate.verify(side, spec, stage)
        if stage == "no_allow":
            self._no_allow_verified.add(side)
        elif stage == "no_receiver":
            self._no_receiver_verified.add(side)
        return outcome

    def apply(self, side, command):
        operation = self.delegate.contract.classify(side, command)
        if operation == "delete_receiver":
            if (side not in self._inactive_verified
                    or side not in self._no_allow_verified):
                raise ChlauthPlanError(
                    "Receiver deletion denied: offline cleanup evidence missing"
                )
            # Re-evaluate immediately before forwarding to the in-memory fake.
            # No claim of atomicity or exclusive ownership is made.
            verify_receiver_cleanup_readbacks(
                self.plan, side, self.readback_provider(side)
            )
        if operation == "remove_deny" and side not in self._no_receiver_verified:
            raise ChlauthPlanError(
                "Deny removal refused until receiver absence is verified"
            )

        # Any attempted mutation invalidates an earlier inactivity readback.
        self._inactive_verified.discard(side)
        if operation in ("add_allow", "remove_allow", "define_receiver"):
            self._no_allow_verified.discard(side)
        if operation in ("define_receiver", "delete_receiver"):
            self._no_receiver_verified.discard(side)
        outcome = self.delegate.apply(side, command)
        if operation == "delete_receiver":
            self._delete_completed.add(side)
        elif operation == "define_receiver":
            self._delete_completed.discard(side)
        return outcome
