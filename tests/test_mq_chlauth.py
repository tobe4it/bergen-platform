"""Offline safety regression tests for exact-channel CHLAUTH fixture planning.

Run: PYTHONPATH=ansible python3 -m unittest discover -s tests -p 'test_mq_chlauth.py'
"""
import copy
import unittest

from module_utils.bergen_mq_chlauth import (
    ChlauthPlanError, LAB, make_plan, verify_runcheck,
)


def nodes():
    return {side: {"qmgr": node["qmgr"], "host": node["host"], "port": 1414}
            for side, node in LAB.items()}


class ChlauthPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan("BGT.A1B2C3D", nodes())

    def test_receivers_map_opposite_peer_exactly(self):
        a, b = self.plan["a"], self.plan["b"]
        self.assertEqual((a["receiver"], a["mcauser"], a["peer_ip"]),
                         ("BGT.A1B2C3D.B2A", "bgttransa", "192.168.20.156"))
        self.assertEqual((b["receiver"], b["mcauser"], b["peer_ip"]),
                         ("BGT.A1B2C3D.A2B", "bgttransb", "192.168.20.212"))
        self.assertIn("SSLCAUTH(REQUIRED)", a["define_receiver"])
        self.assertIn("CERTLABL('bergentransport')", b["define_receiver"])

    def test_each_direction_has_reject_fallback_and_certificate_bound_allow(self):
        for side, fixture in self.plan.items():
            self.assertEqual(len(fixture["add_rules"]), 2)
            deny, allow = fixture["add_rules"]
            self.assertIn("TYPE(ADDRESSMAP) ADDRESS('*') USERSRC(NOACCESS)", deny)
            self.assertIn("TYPE(SSLPEERMAP)", allow)
            for expected in ("SSLPEER(", "SSLCERTI(", "ADDRESS(",
                             "USERSRC(MAP)", "MCAUSER("):
                self.assertIn(expected, allow)
            self.assertIn(fixture["mcauser"], allow)
            self.assertTrue(all("CHLAUTH('%s')" % fixture["receiver"] in s
                                for s in fixture["add_rules"]))
            self.assertNotIn("CHLAUTH('BGT.CLIENT')", " ".join(fixture["add_rules"]))
            self.assertEqual([c["expect"] for c in fixture["cases"]],
                             ["MAP", "NOACCESS", "NOACCESS", "NOACCESS"])
            self.assertEqual({c["name"] for c in fixture["cases"]},
                             {"valid_certificate", "wrong_subject",
                              "wrong_issuer", "wrong_source_ip"})

    def test_all_cleanup_references_exact_owned_receiver(self):
        for fixture in self.plan.values():
            self.assertEqual(len(fixture["cleanup"]), 3)
            for command in fixture["cleanup"]:
                self.assertIn("('%s')" % fixture["receiver"], command)
                self.assertNotIn("REMOVEALL", command)
                self.assertNotIn("BGT.*", command)
            self.assertIn("ACTION(REMOVE)", fixture["cleanup"][0])

    def test_invalid_prefix_and_injection_rejected(self):
        for prefix in ("BGT.*", "BGT.CLIENT", "BGT.abcdef0",
                       "BGT.A1B2C3D'; DELETE QMGR", "BGT.A1B2C3",
                       "BGT.A1B2C3D\n"):
            with self.subTest(prefix=prefix):
                with self.assertRaises(ChlauthPlanError):
                    make_plan(prefix, nodes())

    def test_changed_peer_ip_and_unknown_qmgr_rejected(self):
        for side in ("a", "b"):
            changed = copy.deepcopy(nodes())
            changed[side]["host"] = "192.168.20.1"
            with self.assertRaises(ChlauthPlanError):
                make_plan("BGT.A1B2C3D", changed)
            changed = copy.deepcopy(nodes())
            changed[side]["qmgr"] = "UNREVIEWED"
            with self.assertRaises(ChlauthPlanError):
                make_plan("BGT.A1B2C3D", changed)

    def test_no_live_mq_mutation_or_network_code_in_module(self):
        import inspect
        import module_utils.bergen_mq_chlauth as module
        code = inspect.getsource(module)
        for forbidden in ("subprocess", "os.system", "paramiko", "requests",
                          "socket.", "runmqsc(", "setmqaut("):
            self.assertNotIn(forbidden, code)

    def test_mqsc_evidence_requires_exact_mapping(self):
        rcvr = self.plan["a"]["receiver"]
        sample = (
            "AMQ8878I: Display channel authentication record details.\n"
            "CHLAUTH(%s) TYPE(SSLPEERMAP)\n" % rcvr +
            "USERSRC(MAP) MCAUSER(bgttransa)\n"
            "No commands have a syntax error.\n"
        )
        self.assertTrue(verify_runcheck(sample, rcvr, "MAP", "bgttransa"))
        with self.assertRaises(ChlauthPlanError):
            verify_runcheck(sample.replace("bgttransa", "mqm"),
                            rcvr, "MAP", "bgttransa")
        with self.assertRaises(ChlauthPlanError):
            verify_runcheck(sample + "AMQ9519E: Channel not found.",
                            rcvr, "MAP", "bgttransa")
        with self.assertRaises(ChlauthPlanError):
            verify_runcheck(sample.replace("TYPE(SSLPEERMAP)", "TYPE(ADDRESSMAP)"),
                            rcvr, "MAP", "bgttransa")

    def test_deny_evidence_requires_addressmap_noaccess(self):
        rcvr = self.plan["b"]["receiver"]
        sample = (
            "AMQ8878I: Display channel authentication record details.\n"
            "CHLAUTH(%s) TYPE(ADDRESSMAP)\n" % rcvr +
            "ADDRESS(*) USERSRC(NOACCESS)\n"
            "No commands have a syntax error.\n"
        )
        self.assertTrue(verify_runcheck(sample, rcvr, "NOACCESS"))
        with self.assertRaises(ChlauthPlanError):
            verify_runcheck(sample.replace("NOACCESS", "CHANNEL"), rcvr, "NOACCESS")


if __name__ == "__main__":
    unittest.main()
