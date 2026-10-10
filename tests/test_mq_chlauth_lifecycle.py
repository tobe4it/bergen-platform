"""Pure offline fault-injection tests for CHLAUTH lifecycle. No MQ access."""
import unittest

from module_utils.bergen_mq_chlauth import LAB, make_plan
from module_utils.bergen_mq_chlauth_lifecycle import (
    ChlauthFixtureLifecycle, FixtureLifecycleError,
)


def plan():
    return make_plan(
        "AUDIT.A1B2C3D",
        {side: {"host": attrs["host"], "qmgr": attrs["qmgr"], "port": 1414}
         for side, attrs in LAB.items()},
    )


class FakeAdapter:
    def __init__(self, fail=None):
        self.events = []
        self.fail = fail
        self.preflight_ok = True

    def _call(self, side, op, detail):
        self.events.append((side, op, detail))
        if self.fail == (side, op, detail):
            raise RuntimeError("simulated failure in %s %s" % (op, detail))

    def preflight(self, side, spec):
        self._call(side, "preflight", spec["receiver"])

    def apply(self, side, statement):
        if "ACTION(REMOVE)" in statement:
            kind = "remove_allow" if "SSLPEERMAP" in statement else "remove_deny"
        elif statement.startswith("DELETE CHANNEL"):
            kind = "delete_receiver"
        elif statement.startswith("DEFINE CHANNEL"):
            kind = "create_receiver"
        else:
            kind = "add_allow" if "SSLPEERMAP" in statement else "add_deny"
        self._call(side, "apply", kind)

    def verify(self, side, spec, stage):
        self._call(side, "verify", stage)

    def check(self, side, case):
        self._call(side, "check", case["name"])


class LifecycleTests(unittest.TestCase):
    def test_success_preflight_both_then_fail_closed_writes_and_cleanup(self):
        a = FakeAdapter()
        states = ChlauthFixtureLifecycle(plan(), a).run()
        self.assertTrue(all(s.verified for s in states.values()))
        self.assertEqual([x[:2] for x in a.events[:2]],
                         [("a", "preflight"), ("b", "preflight")])
        for side in ("a", "b"):
            actions = [x[2] for x in a.events if x[0] == side and x[1] == "apply"]
            self.assertEqual(actions,
                             ["add_deny", "create_receiver", "add_allow",
                              "remove_allow", "delete_receiver", "remove_deny"])
            checks = [x[2] for x in a.events if x[0] == side and x[1] == "check"]
            self.assertEqual(checks, [
                "valid_certificate", "wrong_subject",
                "wrong_issuer", "wrong_source_ip"
            ])

    def test_preflight_failure_prevents_all_writes(self):
        a = FakeAdapter(fail=("b", "preflight", plan()["b"]["receiver"]))
        with self.assertRaises(RuntimeError):
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertFalse(any(event[1] == "apply" for event in a.events))

    def test_negative_runcheck_failure_rolls_back_both_sides(self):
        a = FakeAdapter(fail=("b", "check", "wrong_issuer"))
        with self.assertRaises(FixtureLifecycleError) as context:
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertTrue(all(s.verified for s in context.exception.states.values()))
        for side in ("a", "b"):
            self.assertIn((side, "apply", "remove_deny"), a.events)

    def test_failed_receiver_delete_retains_deny(self):
        a = FakeAdapter(fail=("b", "apply", "delete_receiver"))
        with self.assertRaises(FixtureLifecycleError) as context:
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertFalse(context.exception.states["b"].verified)
        self.assertTrue(context.exception.states["a"].verified)
        self.assertNotIn(("b", "apply", "remove_deny"), a.events)
        self.assertIn(("a", "apply", "remove_deny"), a.events)

    def test_ambiguous_receiver_deletion_verification_retains_deny(self):
        a = FakeAdapter(fail=("a", "verify", "no_receiver"))
        with self.assertRaises(FixtureLifecycleError):
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertNotIn(("a", "apply", "remove_deny"), a.events)

    def test_allow_remove_failure_retains_deny(self):
        a = FakeAdapter(fail=("b", "apply", "remove_allow"))
        with self.assertRaises(FixtureLifecycleError):
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertNotIn(("b", "apply", "remove_deny"), a.events)

    def test_uncertain_receiver_creation_is_registered_for_cleanup(self):
        a = FakeAdapter(fail=("a", "apply", "create_receiver"))
        with self.assertRaises(FixtureLifecycleError):
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertIn(("a", "verify", "receiver_inactive"), a.events)
        self.assertIn(("a", "apply", "delete_receiver"), a.events)

    def test_uncertain_allow_grant_is_registered_for_cleanup(self):
        a = FakeAdapter(fail=("a", "apply", "add_allow"))
        with self.assertRaises(FixtureLifecycleError):
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertIn(("a", "apply", "remove_allow"), a.events)

    def test_failed_inactive_check_keeps_deny(self):
        a = FakeAdapter(fail=("a", "verify", "receiver_inactive"))
        with self.assertRaises(FixtureLifecycleError):
            ChlauthFixtureLifecycle(plan(), a).run()
        self.assertNotIn(("a", "apply", "delete_receiver"), a.events)
        self.assertNotIn(("a", "apply", "remove_deny"), a.events)


if __name__ == "__main__":
    unittest.main()
