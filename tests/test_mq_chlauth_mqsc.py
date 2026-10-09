"""Offline IBM MQ MQSC output contracts: no live connectivity or mutations."""
import unittest

from module_utils.bergen_mq_chlauth import LAB, ChlauthPlanError, make_plan
from module_utils.bergen_mq_chlauth_mqsc import (
    require_success, channel_auth_records, exact_records,
    require_exact_fixture_records, require_receiver_definition,
)

TAIL = (
    "One MQSC command read.\n"
    "No commands have a syntax error.\n"
    "All valid MQSC commands were processed.\n"
)
INTRO = (
    "5724-H72 (C) Copyright IBM Corp. 1994, 2026.\n"
    "Starting MQSC for queue manager BERGENLAB.\n\n"
)
PLAN = make_plan("BGT.A1B2C3D", {
    side: {"host": entry["host"], "qmgr": entry["qmgr"], "port": 1414}
    for side, entry in LAB.items()
})
SPEC = PLAN["a"]


def record(data):
    return (
        "AMQ8878I: Display channel authentication record details.\n"
        + "\n".join("   %s(%s)" % pair for pair in data.items()) + "\n"
    )


DENY = {
    "CHLAUTH": SPEC["receiver"], "TYPE": "ADDRESSMAP", "ADDRESS": "*",
    "USERSRC": "NOACCESS", "WARN": "NO",
}
ALLOW = {
    "CHLAUTH": SPEC["receiver"], "TYPE": "SSLPEERMAP",
    "SSLPEER": SPEC["peer_subject"], "SSLCERTI": SPEC["peer_issuer"],
    "ADDRESS": SPEC["peer_ip"], "USERSRC": "MAP",
    "MCAUSER": SPEC["mcauser"], "WARN": "NO",
}
UNRELATED = {
    "CHLAUTH": "BGT.CLIENT", "TYPE": "ADDRESSMAP",
    "ADDRESS": "*", "USERSRC": "NOACCESS", "WARN": "NO",
}


class MqscEvidenceTests(unittest.TestCase):
    def test_strict_single_command_completion(self):
        self.assertEqual(require_success(0, INTRO + TAIL), INTRO + TAIL)
        for rc, text in [
            (10, INTRO + TAIL),
            (0, INTRO + "No commands have a syntax error.\n"),
            (0, INTRO + TAIL + TAIL),
            (0, INTRO + "AMQ9519E: Channel missing.\n" + TAIL),
            (0, INTRO + "One valid MQSC command could not be processed.\n" + TAIL),
            (0, INTRO + TAIL.replace(
                "All valid MQSC commands were processed.", "Some commands were not processed.")),
        ]:
            with self.subTest(rc=rc, text=text):
                with self.assertRaises(ChlauthPlanError):
                    require_success(rc, text)

    def test_exact_chlauth_snapshot(self):
        output = INTRO + record(UNRELATED) + record(DENY) + record(ALLOW) + TAIL
        parsed = channel_auth_records(0, output)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(exact_records(parsed, SPEC["receiver"]), [DENY, ALLOW])
        self.assertTrue(require_exact_fixture_records(parsed, SPEC, "allow"))
        self.assertTrue(require_exact_fixture_records(
            channel_auth_records(0, INTRO + record(DENY) + TAIL), SPEC, "deny"))
        self.assertTrue(require_exact_fixture_records(
            channel_auth_records(0, INTRO + record(UNRELATED) + TAIL), SPEC, "clean"))

    def test_reject_missing_extra_or_wrong_mapping(self):
        for wrong in (
            dict(ALLOW, MCAUSER="mqm"),
            dict(ALLOW, SSLCERTI="CN=Untrusted"),
            dict(ALLOW, SSLPEER="CN=Unknown"),
            dict(ALLOW, ADDRESS="192.168.20.42"),
            dict(ALLOW, USERSRC="CHANNEL"),
            dict(ALLOW, WARN="YES"),
        ):
            with self.subTest(wrong=wrong):
                with self.assertRaises(ChlauthPlanError):
                    require_exact_fixture_records(
                        [DENY, wrong], SPEC, "allow")
        for snapshot in ([DENY, DENY], [ALLOW], [DENY, ALLOW, ALLOW]):
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ChlauthPlanError):
                    require_exact_fixture_records(snapshot, SPEC, "deny")
        with self.assertRaises(ChlauthPlanError):
            require_exact_fixture_records([DENY], SPEC, "clean")

    def test_reject_ambiguous_or_truncated_chlauth_records(self):
        with self.assertRaises(ChlauthPlanError):
            channel_auth_records(0, INTRO + TAIL)
        with self.assertRaises(ChlauthPlanError):
            channel_auth_records(0, INTRO + record(DENY) + "   WARN(YES)\n" + TAIL)
        with self.assertRaises(ChlauthPlanError):
            channel_auth_records(0, INTRO + "AMQ8878I: Display channel authentication record details.\n" + TAIL)

    def test_receiver_tls_identity_readback(self):
        output = (
            INTRO +
            "AMQ8414I: Display Channel details.\n"
            "   CHANNEL(%s) CHLTYPE(RCVR)\n"
            "   SSLCIPH(TLS_AES_256_GCM_SHA384) SSLCAUTH(REQUIRED)\n"
            "   CERTLABL(bergentransport) MCAUSER(bgttransa)\n" % SPEC["receiver"]
            + TAIL
        )
        self.assertTrue(require_receiver_definition(0, output, SPEC))
        with self.assertRaises(ChlauthPlanError):
            require_receiver_definition(
                0, output.replace("MCAUSER(bgttransa)", "MCAUSER(mqm)"), SPEC)
        with self.assertRaises(ChlauthPlanError):
            require_receiver_definition(
                0, output.replace("SSLCAUTH(REQUIRED)", "SSLCAUTH(OPTIONAL)"), SPEC)
        with self.assertRaises(ChlauthPlanError):
            require_receiver_definition(10, output, SPEC)


if __name__ == "__main__":
    unittest.main()
