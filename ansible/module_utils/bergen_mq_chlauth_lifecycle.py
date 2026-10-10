"""Fail-closed lifecycle for exact run-owned MQ CHLAUTH fixtures.

No network access. A runtime adapter must implement the documented methods.
All ownership proofs and successful MQSC command processing are adapter
responsibilities, not inferred from the attempted command.

Live integration is intentionally separate: this module must not be invoked
as a standalone MQ mutator before an approved, reviewed adapter exists.
"""
from dataclasses import dataclass, field

from .bergen_mq_chlauth import ChlauthPlanError


@dataclass
class SideState:
    side: str
    receiver: str
    deny_attempted: bool = False
    receiver_attempted: bool = False
    allow_attempted: bool = False
    deny_removed: bool = False
    receiver_removed: bool = False
    allow_removed: bool = False
    verified: bool = False
    errors: list = field(default_factory=list)


class FixtureLifecycleError(RuntimeError):
    def __init__(self, message, states):
        super().__init__(message)
        self.states = states


class ChlauthFixtureLifecycle:
    """Operation/rollback ordering with pessimistic ownership accounting.

    Adapter methods:
      preflight(side, spec): require expected absent exact receiver AND rules,
                            compare baseline, CHLAUTH enabled, certificate.
      apply(side, statement): execute exact single MQSC; error on unexpected
                              response, ambiguity or disconnect.
      check(side, case): execute MATCH(RUNCHECK) and verify exact result.
      verify(side, spec, stage): independent readback. stage is 'deny',
                               'receiver', 'allow', 'no_allow', 'no_receiver',
                               'clean'. 'no_receiver' MUST prove channel
                               inactive and absent; 'clean' proves all three
                               fixture records absent and baseline intact.
    Adapter must not claim a successful delete unless both non-running channel
    status and exact-object absence are positively verified.
    """

    def __init__(self, plan, adapter):
        if not isinstance(plan, dict) or set(plan) != {"a", "b"}:
            raise ChlauthPlanError("Exactly two receiver plans required")
        for side, spec in plan.items():
            if (spec.get("receiver", "").startswith("AUDIT.") is not True
                    or len(spec.get("apply_order", [])) != 3
                    or len(spec.get("cleanup", [])) != 3
                    or len(spec.get("cases", [])) != 4):
                raise ChlauthPlanError("Incomplete receiver lifecycle plan")
        self.plan = plan
        self.adapter = adapter
        self.states = {
            side: SideState(side, plan[side]["receiver"])
            for side in ("a", "b")
        }

    def _mark(self, state, attribute):
        # An uncertain write outcome must be treated as a possibly applied
        # mutation. The flag is armed BEFORE calling the adapter.
        setattr(state, attribute, True)

    def _cleanup(self, side):
        spec, state = self.plan[side], self.states[side]
        allow_remove, receiver_delete, deny_remove = spec["cleanup"]
        safe_for_deny_removal = True

        if state.allow_attempted:
            try:
                self.adapter.apply(side, allow_remove)
                self.adapter.verify(side, spec, "no_allow")
                state.allow_removed = True
            except Exception as exc:
                state.errors.append("remove SSLPEERMAP: " + str(exc))
                safe_for_deny_removal = False

        if state.receiver_attempted:
            try:
                # Adapter must verify inactive/non-in-doubt receiver FIRST.
                self.adapter.verify(side, spec, "receiver_inactive")
                self.adapter.apply(side, receiver_delete)
                self.adapter.verify(side, spec, "no_receiver")
                state.receiver_removed = True
            except Exception as exc:
                state.errors.append("delete receiver: " + str(exc))
                safe_for_deny_removal = False

        # If any possible receiver or allow rule remains, keep the deny rule.
        if state.deny_attempted and safe_for_deny_removal:
            try:
                self.adapter.apply(side, deny_remove)
                self.adapter.verify(side, spec, "clean")
                state.deny_removed = True
            except Exception as exc:
                state.errors.append("remove ADDRESSMAP deny: " + str(exc))
        elif state.deny_attempted:
            state.errors.append(
                "RETAIN ADDRESSMAP(NOACCESS): receiver/SSLPEERMAP absence not proven"
            )

        # When nothing was attempted the baseline is necessarily unchanged.
        if not state.deny_attempted and not state.receiver_attempted and not state.allow_attempted:
            state.verified = True
        else:
            state.verified = (not state.errors and state.deny_removed
                              and (not state.receiver_attempted or state.receiver_removed)
                              and (not state.allow_attempted or state.allow_removed))
        return state.verified

    def run(self):
        # All preflights must pass BEFORE the first mutation.
        for side in ("a", "b"):
            self.adapter.preflight(side, self.plan[side])

        original_error = None
        try:
            for side in ("a", "b"):
                spec, state = self.plan[side], self.states[side]
                deny, receiver, allow = spec["apply_order"]

                self._mark(state, "deny_attempted")
                self.adapter.apply(side, deny)
                self.adapter.verify(side, spec, "deny")

                self._mark(state, "receiver_attempted")
                self.adapter.apply(side, receiver)
                self.adapter.verify(side, spec, "receiver")

                self._mark(state, "allow_attempted")
                self.adapter.apply(side, allow)
                self.adapter.verify(side, spec, "allow")

                for case in spec["cases"]:
                    self.adapter.check(side, case)
        except Exception as exc:
            original_error = exc
        finally:
            # Cleanup both sides even if only one side was modified.
            for side in ("b", "a"):
                try:
                    self._cleanup(side)
                except Exception as exc:
                    self.states[side].errors.append("unexpected cleanup error: " + str(exc))
                    self.states[side].verified = False

        if original_error or not all(s.verified for s in self.states.values()):
            problems = [
                "%s: %s" % (side, "; ".join(state.errors) or "test failed")
                for side, state in self.states.items()
                if state.errors or not state.verified
            ]
            if original_error:
                problems.insert(0, "fixture/test error: " + str(original_error))
            raise FixtureLifecycleError(
                "FAIL / review retained fixture state: " + " | ".join(problems),
                self.states,
            )
        return self.states
