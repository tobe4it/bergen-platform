"""Offline tests for read-only CHLAUTH adapter, using injected MQSC output."""
import unittest

from module_utils.bergen_mq_chlauth import LAB, ChlauthPlanError, make_plan
from module_utils.bergen_mq_chlauth_readonly import ReadOnlyChlauthAdapter

TAIL = ("One MQSC command read.\n"
        "No commands have a syntax error.\n"
        "All valid MQSC commands were processed.\n")
MISSING_TAIL = ("One MQSC command read.\n"
                "No commands have a syntax error.\n"
                "One valid MQSC command could not be processed.\n")


def fixture():
    return make_plan("BGT.A1B2C3D", {
        side: {"qmgr": data["qmgr"], "host": data["host"], "port": 1414}
        for side, data in LAB.items()
    })


def rules(extra=""):
    return ("AMQ8878I: Display channel authentication record details.\n"
            "   CHLAUTH(BGT.CLIENT) TYPE(ADDRESSMAP) ADDRESS(*) USERSRC(NOACCESS)\n"
            "AMQ8878I: Display channel authentication record details.\n"
            "   CHLAUTH(*) TYPE(BLOCKUSER) USERLIST(*MQADMIN)\n"
            + extra + TAIL)


def mock_run(side, command):
    if command == "DISPLAY QMGR CHLAUTH CERTLABL":
        return 0, ("Starting MQSC for queue manager %s.\n"
                   "AMQ8408I: Display Queue Manager details.\n"
                   "   CHLAUTH(ENABLED) CERTLABL(bergenlab)\n" % LAB[side]["qmgr"] + TAIL)
    if command.startswith("DISPLAY CHANNEL("):
        return 10, ("AMQ8147E: IBM MQ object not found.\n" + MISSING_TAIL)
    if command == "DISPLAY CHLAUTH(*) ALL":
        return 0, rules()
    raise AssertionError("Unexpected command " + command)


class ReadOnlyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()

    def test_both_sides_succeed_read_only(self):
        observed = []
        def runner(side, command):
            observed.append((side, command))
            return mock_run(side, command)
        adapter = ReadOnlyChlauthAdapter(runner)
        for side in ("a", "b"):
            result = adapter.preflight(side, self.spec[side])
            self.assertTrue(result["receiver_absent"])
            self.assertTrue(result["exact_rules_absent"])
            self.assertEqual(result["qmgr"], LAB[side]["qmgr"])
        self.assertEqual(len(observed), 6)
        self.assertTrue(all(command.startswith("DISPLAY ") for _, command in observed))

    def test_write_and_lifecycle_methods_fail_closed(self):
        adapter = ReadOnlyChlauthAdapter(mock_run)
        with self.assertRaises(ChlauthPlanError):
            adapter.apply("a", self.spec["a"]["add_rules"][0])
        with self.assertRaises(ChlauthPlanError):
            adapter.check("a", self.spec["a"]["cases"][0])
        with self.assertRaises(ChlauthPlanError):
            adapter.verify("a", self.spec["a"], "allow")
        with self.assertRaises(ChlauthPlanError):
            adapter._display("a", "SET CHLAUTH('BGT.X') TYPE(ADDRESSMAP)")
        with self.assertRaises(ChlauthPlanError):
            adapter._display("a", "DISPLAY QMGR\nSET CHLAUTH('BGT.X') TYPE(ADDRESSMAP)")

    def test_existing_receiver_refused(self):
        def runner(side, command):
            if command.startswith("DISPLAY CHANNEL("):
                return 0, "AMQ8414I: Display Channel details.\n" + TAIL
            return mock_run(side, command)
        with self.assertRaises(ChlauthPlanError):
            ReadOnlyChlauthAdapter(runner).preflight("a", self.spec["a"])

    def test_preexisting_exact_chlauth_rule_refused(self):
        def runner(side, command):
            if command == "DISPLAY CHLAUTH(*) ALL":
                entry = ("AMQ8878I: Display channel authentication record details.\n"
                         "   CHLAUTH(BGT.A1B2C3D.B2A) TYPE(ADDRESSMAP)\n"
                         "   ADDRESS(*) USERSRC(NOACCESS)\n")
                return 0, rules(entry)
            return mock_run(side, command)
        with self.assertRaises(ChlauthPlanError):
            ReadOnlyChlauthAdapter(runner).preflight("a", self.spec["a"])

    def test_missing_default_client_rule_refused(self):
        def runner(side, command):
            if command == "DISPLAY CHLAUTH(*) ALL":
                return 0, ("AMQ8878I: Display channel authentication record details.\n"
                           "   CHLAUTH(*) TYPE(BLOCKUSER) USERLIST(*MQADMIN)\n" + TAIL)
            return mock_run(side, command)
        with self.assertRaises(ChlauthPlanError):
            ReadOnlyChlauthAdapter(runner).preflight("b", self.spec["b"])

    def test_non_success_or_unknown_missing_error_refused(self):
        for changed in (
            lambda: (10, "AMQ9519E: Unknown channel.\n" + MISSING_TAIL),
            lambda: (10, "AMQ8147E: Missing.\nAMQ9519E: Other.\n" + MISSING_TAIL),
            lambda: (0, "AMQ8147E: Missing.\n" + MISSING_TAIL),
        ):
            def runner(side, command):
                if command.startswith("DISPLAY CHANNEL("):
                    return changed()
                return mock_run(side, command)
            with self.subTest(changed=changed):
                with self.assertRaises(ChlauthPlanError):
                    ReadOnlyChlauthAdapter(runner).preflight("a", self.spec["a"])

    def test_wrong_queue_manager_and_unsafe_name_refused(self):
        wrong = dict(self.spec["a"], qmgr="BERGENLABB")
        with self.assertRaises(ChlauthPlanError):
            ReadOnlyChlauthAdapter(mock_run).preflight("a", wrong)
        wrong = dict(self.spec["a"], receiver="BGT.CLIENT")
        with self.assertRaises(ChlauthPlanError):
            ReadOnlyChlauthAdapter(mock_run).preflight("a", wrong)


if __name__ == "__main__":
    unittest.main()
