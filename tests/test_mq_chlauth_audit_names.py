"""Offline namespace contracts for run-scoped AUDIT fixtures."""
import unittest

from module_utils.bergen_mq_audit_names import (
    CHANNEL_LIMIT, QUEUE_LIMIT, alias_queue, channel_name,
    local_queue, remote_queue, transmission_queue, validate_run,
)


class AuditNameTests(unittest.TestCase):
    def test_expected_names_and_lengths(self):
        run = validate_run("AUDIT.A1B2C3D")
        self.assertEqual(channel_name(run, "a", "b"), "AUDIT.A1B2C3D.A2B")
        self.assertEqual(channel_name(run, "b", "a"), "AUDIT.A1B2C3D.B2A")
        self.assertEqual(local_queue(run, "B.PERSISTENT.IN"),
                         "LQ.AUDIT.A1B2C3D.B.PERSISTENT.IN")
        self.assertEqual(alias_queue(run, "B.PERSISTENT.IN"),
                         "AUDIT.A1B2C3D.B.PERSISTENT.IN")
        self.assertEqual(remote_queue(run, "A.PERSISTENT.REMOTE"),
                         "RQ.AUDIT.A1B2C3D.A.PERSISTENT.REMOTE")
        self.assertEqual(transmission_queue(run, "a"), "XQ.AUDIT.A1B2C3D.AX")
        self.assertLessEqual(len(channel_name(run, "a", "b")), CHANNEL_LIMIT)
        for name in (
            local_queue(run, "B.PERSISTENT.IN"),
            alias_queue(run, "B.PERSISTENT.IN"),
            remote_queue(run, "A.PERSISTENT.REMOTE"),
            transmission_queue(run, "b"),
        ):
            self.assertLessEqual(len(name), QUEUE_LIMIT)

    def test_reject_inherited_bgt_or_unreviewed_prefixes(self):
        for name in ("BGT.A1B2C3D", "BGT.CLIENT", "AUDIT.*",
                     "AUDIT.abcdef0", "AUDIT.A1B2C3", "AUDIT.A1B2C3D\n"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_run(name)

    def test_reject_invalid_direction_and_suffix(self):
        run = "AUDIT.A1B2C3D"
        with self.assertRaises(ValueError):
            channel_name(run, "a", "a")
        with self.assertRaises(ValueError):
            transmission_queue(run, "c")
        for suffix in ("", "a0", "A..B", "A'); DELETE QMGR", "A" * 49):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):
                    alias_queue(run, suffix)

    def test_aliases_are_scoped_and_distinct_from_physical_queues(self):
        run = "AUDIT.A1B2C3D"
        alias = alias_queue(run, "A0")
        physical = local_queue(run, "A0")
        self.assertNotEqual(alias, physical)
        self.assertEqual(alias, physical.removeprefix("LQ."))
        self.assertNotEqual(alias, alias_queue("AUDIT.B2B2B2B", "A0"))


if __name__ == "__main__":
    unittest.main()
