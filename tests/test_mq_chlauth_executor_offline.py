import tempfile
import unittest
from pathlib import Path

from module_utils.bergen_mq_chlauth import ChlauthPlanError
from module_utils.bergen_mq_chlauth_journal import (
    LockedFixtureJournal, read_journal,
)
from module_utils.bergen_mq_chlauth_write_contract import (
    ApprovedCommandContract, canonical_plan,
)
from module_utils.bergen_mq_chlauth_executor_offline import (
    InMemoryMqscRunner, JournaledOfflineMqscExecutor,
)

SUCCESS = (
    "One MQSC command read.\n"
    "No commands have a syntax error.\n"
    "All valid MQSC commands were processed.\n"
)


class OfflineExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "journal"
        self.plan = canonical_plan()
        self.contract = ApprovedCommandContract(self.plan)
        self.command = self.plan["a"]["apply_order"][0]

    def executor(self, journal, outcome):
        runner = InMemoryMqscRunner({
            ("a", self.command): outcome
        })
        return (
            JournaledOfflineMqscExecutor(
                runner, journal, self.contract
            ),
            runner,
        )

    def test_valid_command_acknowledged(self):
        with LockedFixtureJournal(
            self.root, "AUDIT.A1B2C3D"
        ) as journal:
            executor, runner = self.executor(
                journal, (0, SUCCESS)
            )
            self.assertEqual(
                executor.apply("a", self.command), "add_deny"
            )
            self.assertEqual(len(runner.calls), 1)
            entries = read_journal(journal.path)
            self.assertEqual(
                entries[-1]["data"]["status"], "ACKED"
            )

    def test_unapproved_command_never_reaches_runner(self):
        with LockedFixtureJournal(
            self.root, "AUDIT.A1B2C3D"
        ) as journal:
            executor, runner = self.executor(
                journal, (0, SUCCESS)
            )
            with self.assertRaises(ChlauthPlanError):
                executor.apply(
                    "a", "ALTER QMGR CHLAUTH(DISABLED)"
                )
            self.assertEqual(runner.calls, [])

    def test_nonzero_rc_blocks_followup_writes(self):
        with LockedFixtureJournal(
            self.root, "AUDIT.A1B2C3D"
        ) as journal:
            executor, runner = self.executor(
                journal, (10, SUCCESS)
            )
            with self.assertRaises(ChlauthPlanError):
                executor.apply("a", self.command)
            with self.assertRaisesRegex(
                ChlauthPlanError, "manual recovery"
            ):
                executor.apply("a", self.command)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(
                read_journal(journal.path)[-1]["data"]["status"],
                "UNKNOWN",
            )

    def test_runner_exception_blocks_followup_writes(self):
        with LockedFixtureJournal(
            self.root, "AUDIT.A1B2C3D"
        ) as journal:
            executor, runner = self.executor(
                journal, TimeoutError("Simulated MQSC timeout")
            )
            with self.assertRaises(TimeoutError):
                executor.apply("a", self.command)
            with self.assertRaises(ChlauthPlanError):
                executor.apply("a", self.command)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(
                read_journal(journal.path)[-1]["data"]["status"],
                "UNKNOWN",
            )
