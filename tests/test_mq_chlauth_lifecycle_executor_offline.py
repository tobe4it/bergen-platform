"""Stateful, fully offline integration test for CHLAUTH and journaled executor."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from module_utils.bergen_mq_chlauth_lifecycle import (
    ChlauthFixtureLifecycle, FixtureLifecycleError,
)
from module_utils.bergen_mq_chlauth_executor_offline import (
    InMemoryMqscRunner, JournaledOfflineMqscExecutor,
)
from module_utils.bergen_mq_chlauth_journal import LockedFixtureJournal, read_journal
from module_utils.bergen_mq_chlauth_write_contract import (
    ApprovedCommandContract, canonical_plan,
)

SUCCESS = (
    "One MQSC command read.\n"
    "No commands have a syntax error.\n"
    "All valid MQSC commands were processed.\n"
)


class ModeledMQ:
    def __init__(self):
        self.objects = {s: dict(deny=False, receiver=False, allow=False)
                        for s in ("a", "b")}
        self.runtime = {s: dict(running=False, in_doubt=False)
                        for s in ("a", "b")}

    def snapshot(self, side):
        return dict(self.objects[side])

    def mutate(self, side, operation):
        state = self.objects[side]
        if operation == "add_deny":
            assert not any(state.values())
            state["deny"] = True
        elif operation == "define_receiver":
            assert state == dict(deny=True, receiver=False, allow=False)
            state["receiver"] = True
        elif operation == "add_allow":
            assert state == dict(deny=True, receiver=True, allow=False)
            state["allow"] = True
        elif operation == "remove_allow":
            assert state == dict(deny=True, receiver=True, allow=True)
            state["allow"] = False
        elif operation == "delete_receiver":
            assert state == dict(deny=True, receiver=True, allow=False)
            state["receiver"] = False
        elif operation == "remove_deny":
            assert state == dict(deny=True, receiver=False, allow=False)
            state["deny"] = False
        else:
            raise AssertionError("Unknown simulated mutation")


class LifecycleBridge:
    """Model-backed readbacks. Never runs Podman, SSH or MQSC."""

    def __init__(self, executor, model, *, corrupt=None):
        self.executor = executor
        self.model = model
        self.corrupt = corrupt

    def preflight(self, side, spec):
        if any(self.model.snapshot(side).values()):
            raise AssertionError("Fixture collision at preflight")

    def apply(self, side, statement):
        return self.executor.apply(side, statement)

    def verify(self, side, spec, stage):
        state = self.model.snapshot(side)
        if (side, stage) == self.corrupt:
            state["allow"] = not state["allow"]
        expected = {
            "deny": (True, False, False),
            "receiver": (True, True, False),
            "allow": (True, True, True),
            "no_allow": (True, True, False),
            "no_receiver": (True, False, False),
            "clean": (False, False, False),
            "receiver_inactive": (True, True, False),
        }
        if stage not in expected:
            raise AssertionError("Unsupported simulated verification: " + stage)
        if stage == "receiver_inactive" and any(self.model.runtime[side].values()):
            raise AssertionError("Receiver is running or in-doubt")
        actual = tuple(state[k] for k in ("deny", "receiver", "allow"))
        if actual != expected[stage]:
            raise AssertionError(f"Readback mismatch {side}/{stage}: {actual}")

    def check(self, side, case):
        state = self.model.snapshot(side)
        if state != dict(deny=True, receiver=True, allow=True):
            raise AssertionError("RUNCHECK on incomplete fixture")
        spec = self.executor.contract.plan[side]
        def field(name):
            match = re.search(r"\b" + name + r"\('([^']+)'\)", case["command"])
            if not match:
                raise AssertionError("Invalid simulated RUNCHECK input")
            return match.group(1)
        correct = (field("ADDRESS") == spec["peer_ip"]
                   and field("SSLPEER") == spec["peer_subject"]
                   and field("SSLCERTI") == spec["peer_issuer"]
                   and field("QMNAME") == spec["peer_qmgr"])
        actual = "MAP" if correct else "NOACCESS"
        if actual != case["expect"]:
            raise AssertionError("RUNCHECK outcome mismatch: " + case["name"])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "journals"
        self.plan = canonical_plan()
        self.contract = ApprovedCommandContract(self.plan)
        self.model = ModeledMQ()
        self.responses = {
            (side, command): (0, SUCCESS)
            for side in ("a", "b")
            for command in self.plan[side]["apply_order"] + self.plan[side]["cleanup"]
        }
        self.runner = InMemoryMqscRunner(self.responses)
        self.path = self.root / "AUDIT.A1B2C3D.jsonl"

    def drive(self, corrupt=None, active_side=None):
        with LockedFixtureJournal(self.root, "AUDIT.A1B2C3D") as journal:
            executor = JournaledOfflineMqscExecutor(
                self.runner, journal, self.contract)
            adapter = LifecycleBridge(executor, self.model, corrupt=corrupt)
            original = self.runner.execute

            def simulated_execution(side, command):
                # Simulated MQ applies the write BEFORE the caller gets its response.
                operation = self.contract.classify(side, command)
                self.model.mutate(side, operation)
                if side == active_side and operation == "define_receiver":
                    self.model.runtime[side]["running"] = True
                return original(side, command)

            with patch.object(self.runner, "execute", side_effect=simulated_execution):
                states = ChlauthFixtureLifecycle(self.plan, adapter).run()
            if not all(s.verified for s in states.values()):
                raise AssertionError("Fixture is not verified clean")
            journal.mark_clean({"a": "VERIFIED_CLEAN", "b": "VERIFIED_CLEAN"})
            return states

    def test_bidirectional_success_and_verified_cleanup(self):
        result = self.drive()
        self.assertTrue(all(s.verified for s in result.values()))
        self.assertEqual(len(self.runner.calls), 12)
        self.assertFalse(any(any(s.values()) for s in self.model.objects.values()))
        self.assertEqual(read_journal(self.path)[-1]["kind"], "CLEAN")

    def test_timeout_after_applied_receiver_blocks_all_future_writes(self):
        cmd = self.plan["a"]["apply_order"][1]
        self.runner.responses[("a", cmd)] = TimeoutError("reply lost after write")
        with self.assertRaises(FixtureLifecycleError):
            self.drive()
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.model.snapshot("a"),
                         dict(deny=True, receiver=True, allow=False))
        self.assertNotEqual(read_journal(self.path)[-1]["kind"], "CLEAN")

    def test_active_receiver_blocks_deletion_and_retains_deny(self):
        with self.assertRaises(FixtureLifecycleError):
            self.drive(active_side="a")
        self.assertTrue(self.model.snapshot("a")["receiver"])
        self.assertTrue(self.model.snapshot("a")["deny"])
        a_commands = [self.contract.classify(side, cmd)
                      for side, cmd in self.runner.calls if side == "a"]
        self.assertNotIn("delete_receiver", a_commands)
        self.assertNotIn("remove_deny", a_commands)
        self.assertNotEqual(read_journal(self.path)[-1]["kind"], "CLEAN")

    def test_false_readback_fails_even_if_writes_acknowledged(self):
        with self.assertRaises(FixtureLifecycleError):
            self.drive(corrupt=("b", "allow"))
        self.assertFalse(any(any(s.values()) for s in self.model.objects.values()))
        self.assertNotEqual(read_journal(self.path)[-1]["kind"], "CLEAN")


if __name__ == "__main__":
    unittest.main()
