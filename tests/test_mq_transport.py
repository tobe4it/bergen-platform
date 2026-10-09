"""Offline contract tests for per-run IBM MQ transport; never contact real QMgr."""
import importlib.util
from pathlib import Path
import unittest

from test_mq import FakeClient, mq, success
from test_mq_topology import topology, transport_module as transport

PREFIX = "AUDIT.ABC1234"


def configured_nodes():
    return {
        "a": {"host": "192.168.20.212", "port": 1414},
        "b": {"host": "192.168.20.156", "port": 1414},
    }


class FakeTransportClient(FakeClient):
    def __init__(self, active, **kwargs):
        super().__init__(**kwargs)
        self.active = active
        self.depth_override = 0
        self.protocol_override = "TLSV13"

    def command(self, command, typ, name, parameters=None, response_parameters=None):
        if command == "display" and typ == "chstatus":
            if name not in self.active:
                return mq_res_missing()
            return success({"channel": name, "status": "RUNNING",
                            "indoubt": "NO",
                            "secprot": self.protocol_override,
                            "sslciph": transport.CIPHER})
        if command == "display" and typ == "qstatus":
            self.calls.append((command, typ, name, parameters, response_parameters))
            return success({"queue": name, "uncom": 0})
        if command == "start" and typ == "channel":
            self.calls.append((command, typ, name, parameters, response_parameters))
            self.active.add(name)
            return success()
        if command == "stop" and typ == "channel":
            self.calls.append((command, typ, name, parameters, response_parameters))
            self.active.discard(name)
            return success()
        if command == "display" and name in self.objects:
            attrs = self.objects[name]
            if attrs.get("usage") == "xmitq":
                attrs["curdepth"] = self.depth_override
        return super().command(command, typ, name, parameters, response_parameters)


def mq_res_missing():
    return {"overallCompletionCode": 2, "overallReasonCode": 3008,
            "commandResponse": [{"completionCode": 2, "reasonCode": 2085}]}


class TransientTransportTests(unittest.TestCase):
    def factory(self):
        active = set()
        return {side: FakeTransportClient(active) for side in ("a", "b")}

    def test_exact_per_run_names_and_two_pairs(self):
        obj = transport.declarations(PREFIX, configured_nodes())
        self.assertEqual(obj["a"]["sender"], PREFIX + ".A2B")
        self.assertEqual(obj["b"]["sender"], PREFIX + ".B2A")
        self.assertEqual(obj["a"]["xmitq"], "XQ." + PREFIX + ".AX")
        self.assertEqual(obj["b"]["xmitq"], "XQ." + PREFIX + ".BX")
        for side in ("a", "b"):
            channels = [o for o in obj[side]["objects"] if o["type"] == "channel"]
            self.assertEqual(len(channels), 2)
            self.assertTrue(all(c["attributes"]["certlabl"] == "bergentransport"
                                for c in channels))
            self.assertEqual(
                {c["attributes"]["chltype"] for c in channels}, {"sdr", "rcvr"})
        for side in ("a", "b"):
            self.assertEqual(len(obj[side]["objects"]), 3)
            self.assertEqual({o["type"] for o in obj[side]["objects"]},
                             {"qlocal", "channel"})
        with self.assertRaises(mq.MQError):
            transport.declarations("AUDIT.BADPREFIX", configured_nodes())

    def test_channel_and_xmitq_name_lengths(self):
        obj = transport.declarations(PREFIX, configured_nodes())
        for side in ("a", "b"):
            self.assertLessEqual(len(obj[side]["sender"]), 20)
            self.assertTrue(obj[side]["sender"].startswith("AUDIT."))
            self.assertLessEqual(len(obj[side]["xmitq"]), 48)
            self.assertTrue(obj[side]["xmitq"].startswith("XQ.AUDIT."))

    def test_collision_refuses_every_mutation(self):
        clients = self.factory()
        name = "XQ." + PREFIX + ".BX"
        clients["b"].objects[name] = {"queue": name, "type": "QLOCAL",
                                     "usage": "xmitq"}
        run = transport.TransientTransport(clients, configured_nodes(), PREFIX)
        with self.assertRaises(mq.MQError):
            run.create()
        for client in clients.values():
            self.assertTrue(all(x[0] == "display" for x in client.calls))

    def test_create_start_verify_tls_and_cleanup(self):
        clients = self.factory()
        run = transport.TransientTransport(clients, configured_nodes(), PREFIX,
                                           sleeper=lambda n: None)
        spec = run.create()
        self.assertEqual(spec["a"]["sender"], PREFIX + ".A2B")
        negotiated = run.start()
        self.assertEqual(negotiated["a"]["protocol"], "TLSV13")
        cleanup, residuals = run.cleanup()
        self.assertEqual(residuals, [])
        self.assertEqual(len(cleanup), 8)  # 2 stops + 6 object deletions
        self.assertTrue(all(row["status"] == "PASS" for row in cleanup))
        self.assertTrue(all(not c.objects for c in clients.values()))
        self.assertFalse(any(call[0] in ("force", "clear") for c in clients.values()
                             for call in c.calls))

    def test_reject_non_tls13_negotiation(self):
        clients = self.factory()
        run = transport.TransientTransport(clients, configured_nodes(), PREFIX,
                                           sleeper=lambda n: None)
        run.create()
        clients["a"].protocol_override = "TLSV12"
        with self.assertRaises(mq.MQError):
            run.start()
        cleanup, residuals = run.cleanup()
        self.assertFalse(residuals)
        self.assertTrue(cleanup)

    def test_nonempty_xmitq_retains_transport_objects(self):
        clients = self.factory()
        run = transport.TransientTransport(clients, configured_nodes(), PREFIX,
                                           sleeper=lambda n: None)
        run.create()
        run.start()
        clients["a"].depth_override = 2
        cleanup, residuals = run.cleanup()
        self.assertTrue(residuals)
        self.assertTrue(any(row["status"] == "FAIL" for row in cleanup))
        self.assertTrue(any(c.objects for c in clients.values()))
        self.assertFalse(any(call[0] == "delete" for c in clients.values()
                             for call in c.calls))

    def test_unknown_indoubt_state_blocks_cleanup(self):
        clients = self.factory()
        run = transport.TransientTransport(clients, configured_nodes(), PREFIX,
                                           sleeper=lambda n: None)
        run.create()
        run.start()
        original = clients["a"].command
        def ambiguous(command, typ, name, parameters=None, response_parameters=None):
            result = original(command, typ, name, parameters, response_parameters)
            if command == "display" and typ == "chstatus" and name == PREFIX + ".A2B":
                if result["commandResponse"][0].get("parameters"):
                    result["commandResponse"][0]["parameters"]["indoubt"] = "YES"
            return result
        clients["a"].command = ambiguous
        cleanup, residuals = run.cleanup()
        self.assertTrue(residuals)
        self.assertFalse(any(call[0] == "delete" for client in clients.values()
                             for call in client.calls))

    def test_uncertain_probe_retains_all(self):
        clients = self.factory()
        run = transport.TransientTransport(clients, configured_nodes(), PREFIX)
        run.create()
        cleanup, residuals = run.cleanup(uncertain=True)
        self.assertEqual(cleanup, [])
        self.assertEqual(len(residuals), 6)
        self.assertTrue(all(not any(call[0] == "delete" for call in c.calls)
                            for c in clients.values()))

    def test_transient_requires_explicit_three_safety_attestations(self):
        from test_mq_topology import nodes
        audit_nodes = nodes()
        with self.assertRaisesRegex(ValueError, "explicit peer firewall"):
            topology.run(audit_nodes, {"host": "client"}, "revision", confirm=True,
                         transient_transport=True)


if __name__ == "__main__":
    unittest.main()
