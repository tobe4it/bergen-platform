"""Stateful, in-memory cleanup readbacks and simulated interleaving faults.

No MQ connection. The fake, its observations and all concurrency injection
are inside one Python process. A passing test does NOT prove the authenticity
of any live MQSC response or absence of a distributed TOCTOU race.
"""
import copy
import tempfile
import unittest
from pathlib import Path

from module_utils.bergen_mq_chlauth_cleanup_lifecycle_offline import (
    OfflineReadbackGatedLifecycleAdapter,
)
from module_utils.bergen_mq_chlauth_journal import (
    LockedFixtureJournal, read_journal,
)
from module_utils.bergen_mq_chlauth_journaled_offline import (
    JournaledOfflineAdapter,
)
from module_utils.bergen_mq_chlauth_lifecycle import (
    ChlauthFixtureLifecycle, FixtureLifecycleError,
)
from module_utils.bergen_mq_chlauth_write_contract import (
    ApprovedCommandContract, canonical_plan,
)
from test_mq_chlauth_cleanup_readback import (
    TAIL, MISSING_TAIL, allow_rule, fixture_evidence, record,
)
from test_mq_chlauth_journaled_offline import InMemoryMQ


class StatefulOfflineMQ(InMemoryMQ):
    """Two simulated queue managers whose writes alter their next readbacks."""

    def __init__(self, plan):
        super().__init__()
        self.contract = ApprovedCommandContract(plan)
        self.state = {
            side: dict(deny=False, receiver=False, allow=False, active=False)
            for side in ("a", "b")
        }
        self.revisions = {"a": 0, "b": 0}

    def snapshot(self, side):
        return dict(self.state[side])

    def interfere(self, side, *, allow=None, active=None):
        state = self.state[side]
        if allow is not None:
            state["allow"] = allow
        if active is not None:
            state["active"] = active
        self.revisions[side] += 1

    def preflight(self, side, spec):
        if any(self.state[side].values()):
            raise AssertionError("Simulated preflight collision")
        return super().preflight(side, spec)

    def apply(self, side, command):
        op = self.contract.classify(side, command)
        state = self.state[side]
        expected = {
            "add_deny": (False, False, False),
            "define_receiver": (True, False, False),
            "add_allow": (True, True, False),
            "remove_allow": (True, True, True),
            "delete_receiver": (True, True, False),
            "remove_deny": (True, False, False),
        }[op]
        actual = tuple(state[k] for k in ("deny", "receiver", "allow"))
        if actual != expected or (op == "delete_receiver" and state["active"]):
            raise AssertionError("Simulated write conflicts with current MQ state")
        result = super().apply(side, command)
        field, value = {
            "add_deny": ("deny", True),
            "define_receiver": ("receiver", True),
            "add_allow": ("allow", True),
            "remove_allow": ("allow", False),
            "delete_receiver": ("receiver", False),
            "remove_deny": ("deny", False),
        }[op]
        state[field] = value
        self.revisions[side] += 1
        return result

    def verify(self, side, spec, stage):
        expected = {
            "deny": (True, False, False),
            "receiver": (True, True, False),
            "allow": (True, True, True),
            "no_allow": (True, True, False),
            "receiver_inactive": (True, True, False),
            "no_receiver": (True, False, False),
            "clean": (False, False, False),
        }[stage]
        state = self.state[side]
        actual = tuple(state[k] for k in ("deny", "receiver", "allow"))
        if actual != expected:
            raise AssertionError("Simulated stage readback disagrees with model")
        if stage == "receiver_inactive" and state["active"]:
            raise AssertionError("Simulated receiver is CURRENT/active")
        return super().verify(side, spec, stage)

    def check(self, side, case):
        state = self.state[side]
        if (state["deny"], state["receiver"], state["allow"]) != (
                True, True, True):
            raise AssertionError("RUNCHECK requires complete simulated fixture")
        return super().check(side, case)


class ModelBackedReadbacks:
    """Freshly synthesize three exact MQSC responses from current model state."""

    def __init__(self, plan, model):
        self.plan = plan
        self.model = model
        self.calls = []

    def __call__(self, side):
        snapshot = self.model.snapshot(side)
        self.calls.append((side, self.model.revisions[side]))
        response = fixture_evidence(self.plan, side)
        spec = self.plan[side]
        denied = record(
            CHLAUTH=spec["receiver"], TYPE="ADDRESSMAP",
            ADDRESS="*", USERSRC="NOACCESS", WARN="NO",
        )
        if not snapshot["deny"]:
            response["rules"]["stdout"] = response["rules"]["stdout"].replace(
                denied, "",
            )
        if snapshot["allow"]:
            response["rules"]["stdout"] = response["rules"]["stdout"].replace(
                TAIL, allow_rule(spec) + TAIL,
            )
        if not snapshot["receiver"]:
            response["channel"]["rc"] = 10
            response["channel"]["stdout"] = (
                "AMQ8147E: IBM MQ object not found.\n" + MISSING_TAIL
            )
        if snapshot["active"]:
            response["current"]["rc"] = 0
            response["current"]["stdout"] = response["current"]["stdout"].replace(
                "AMQ8420I: Channel Status not found.",
                "AMQ8417I: Display Channel Status details.\n"
                "CHANNEL(%s) STATUS(RUNNING)" % spec["receiver"],
            )
        return response


class StatefulCleanupTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name) / "journal"
        self.plan = canonical_plan()
        self.model = StatefulOfflineMQ(self.plan)
        self.probe = ModelBackedReadbacks(self.plan, self.model)

    def run_fixture(self, provider=None):
        with LockedFixtureJournal(self.root, "AUDIT.A1B2C3D") as journal:
            delegated = JournaledOfflineAdapter(
                self.model, journal, ApprovedCommandContract(self.plan),
            )
            bridge = OfflineReadbackGatedLifecycleAdapter(
                self.plan, delegated,
                self.probe if provider is None else provider,
            )
            states = ChlauthFixtureLifecycle(self.plan, bridge).run()
            journal.mark_clean({
                "a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN",
            })
            return states, journal.path

    def assert_failed_and_retained_deny(self, provider, side="b"):
        with self.assertRaises(FixtureLifecycleError):
            self.run_fixture(provider)
        commands = [
            detail for host, action, detail in self.model.events
            if host == side and action == "apply"
        ]
        self.assertNotIn("delete_receiver", commands)
        self.assertNotIn("remove_deny", commands)
        self.assertTrue(self.model.snapshot(side)["deny"])
        path = self.root / "AUDIT.A1B2C3D.jsonl"
        self.assertNotEqual(read_journal(path)[-1]["kind"], "CLEAN")

    def test_model_backed_readbacks_follow_mutations(self):
        side = "a"
        start = self.probe(side)
        self.assertNotIn("AMQ8414I", start["channel"]["stdout"])
        self.assertNotIn(
            "CHLAUTH(%s)" % self.plan[side]["receiver"],
            start["rules"]["stdout"],
        )
        self.model.apply(side, self.plan[side]["apply_order"][0])
        deny = self.probe(side)
        self.assertIn(
            "CHLAUTH(%s)" % self.plan[side]["receiver"],
            deny["rules"]["stdout"],
        )
        self.model.apply(side, self.plan[side]["apply_order"][1])
        receiver = self.probe(side)
        self.assertIn("AMQ8414I", receiver["channel"]["stdout"])
        self.model.apply(side, self.plan[side]["apply_order"][2])
        allowed = self.probe(side)
        self.assertIn("TYPE(SSLPEERMAP)", allowed["rules"]["stdout"])

    def test_stateful_two_side_lifecycle_has_fresh_cleanup_observations(self):
        states, path = self.run_fixture()
        self.assertTrue(all(item.verified for item in states.values()))
        self.assertEqual(
            self.model.snapshot("a"),
            dict(deny=False, receiver=False, allow=False, active=False),
        )
        self.assertEqual(self.model.snapshot("b"), self.model.snapshot("a"))
        self.assertEqual([side for side, _ in self.probe.calls], [
            "b", "b", "a", "a",
        ])
        self.assertEqual(read_journal(path)[-1]["kind"], "CLEAN")

    def test_concurrent_allow_recreated_after_first_readback_blocks_delete(self):
        count = {"b": 0}

        def probe(side):
            result = self.probe(side)
            if side == "b":
                count["b"] += 1
                if count["b"] == 1:
                    # A second actor changes the fake model AFTER the first
                    # snapshot; the cached evidence now describes the past.
                    self.model.interfere(side, allow=True)
            return result

        self.assert_failed_and_retained_deny(probe)
        self.assertEqual(count["b"], 1)

    def test_running_receiver_at_final_readback_blocks_delete(self):
        count = {"b": 0}

        def probe(side):
            if side == "b":
                count["b"] += 1
                if count["b"] == 2:
                    self.model.interfere(side, active=True)
            return self.probe(side)

        self.assert_failed_and_retained_deny(probe)
        self.assertEqual(count["b"], 2)

    def test_replayed_inactive_status_rejected_by_model_verification(self):
        cached = {}
        count = {"b": 0}

        def probe(side):
            if side == "b":
                count["b"] += 1
                if count["b"] == 2:
                    # A conflicting state appears during the final fake probe,
                    # while the provider replays an older all-clear snapshot.
                    self.model.interfere(side, active=True)
                    return copy.deepcopy(cached["b"])
            response = self.probe(side)
            if side == "b":
                cached["b"] = copy.deepcopy(response)
            return response

        self.assert_failed_and_retained_deny(probe)
        self.assertEqual(count["b"], 2)

    def test_conflicting_tls_attribute_at_final_probe_blocks_delete(self):
        count = {"b": 0}

        def probe(side):
            response = self.probe(side)
            if side == "b":
                count["b"] += 1
                if count["b"] == 2:
                    response["channel"]["stdout"] = response["channel"][
                        "stdout"
                    ].replace("SSLCAUTH(REQUIRED)", "SSLCAUTH(OPTIONAL)")
            return response

        self.assert_failed_and_retained_deny(probe)
        self.assertEqual(count["b"], 2)


if __name__ == "__main__":
    unittest.main()
