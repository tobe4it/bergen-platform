"""Offline contract tests; these do not establish IBM MQ compatibility."""
import copy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("bergen_mq", Path(__file__).resolve().parents[1] / "ansible/module_utils/bergen_mq.py")
mq = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mq)


def success(parameters=None):
    row = dict(completionCode=0, reasonCode=0)
    if parameters is not None:
        row["parameters"] = parameters
    return dict(commandResponse=[row], overallCompletionCode=0, overallReasonCode=0)


def missing():
    return dict(commandResponse=[dict(completionCode=2, reasonCode=2085)],
                overallCompletionCode=2, overallReasonCode=3008)


QUEUE = dict(name="BERGEN.EVENTS", type="qlocal", state="present",
             attributes=dict(maxdepth=5000, defpsist="yes"))


class FakeClient:
    def __init__(self, objects=None):
        self.objects = copy.deepcopy(objects or {})
        self.calls = []
        self.fail_on = None
        self.ignore_updates = False

    def command(self, command, typ, name, parameters=None, response_parameters=None):
        self.calls.append((command, typ, name, parameters, response_parameters))
        if self.fail_on == (command, name):
            raise mq.MQError("Injected failure")
        if command == "display":
            return success(self.objects[name]) if name in self.objects else missing()
        if not self.ignore_updates:
            if command == "define":
                key = "queue" if typ.startswith("q") else typ
                self.objects[name] = {key: name, **parameters}
                if key == "queue":
                    self.objects[name]["type"] = typ.upper()
            elif command == "alter":
                self.objects[name].update(parameters)
            elif command == "delete":
                del self.objects[name]
        return success()


class ReconciliationTests(unittest.TestCase):
    def test_safe_http_detail_allowlist_and_bounds(self):
        import json
        payload = {"error": [{"msgId": "MQWB9999E", "message": "Invalid parameter chltable for user xyz",
                              "explanation": "hidden"}], "other": "hidden"}
        result = mq.safe_http_detail(json.dumps(payload).encode(), ("xyz",))
        self.assertIn("Invalid parameter chltable", result)
        self.assertNotIn("xyz", result)
        self.assertNotIn("hidden", result)
        for raw in (b"not JSON", b"[]", b"{}", b"x" * 16385):
            self.assertEqual(mq.safe_http_detail(raw, ()), "")
        payload['error'][0]['message'] = 'Authorization: Basic unknown'
        self.assertNotIn('unknown', mq.safe_http_detail(json.dumps(payload).encode(), ()))

    def queue_client(self, **attrs):
        return FakeClient({QUEUE["name"]: dict(queue=QUEUE["name"], type="QLOCAL", maxdepth=5000, defpsist="YES", **attrs)})

    def test_missing_queue_create_and_second_run_idempotent(self):
        client = FakeClient()
        first = mq.reconcile(client, [QUEUE])
        self.assertTrue(first["changed"])
        self.assertEqual(first["applied"][0]["action"], "define")
        self.assertFalse(mq.reconcile(client, [QUEUE])["changed"])

    def test_only_changed_attributes_altered(self):
        client = self.queue_client()
        obj = copy.deepcopy(QUEUE)
        obj["attributes"]["maxdepth"] = 7000
        result = mq.reconcile(client, [obj])
        self.assertEqual(result["plans"][0]["parameters"], {"maxdepth": 7000})
        self.assertFalse(mq.reconcile(client, [obj])["changed"])

    def test_check_diff_create_never_mutates(self):
        client = FakeClient()
        result = mq.reconcile(client, [QUEUE], check_mode=True)
        self.assertTrue(result["changed"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["diff"][0]["before"], {"state": "absent"})
        self.assertEqual([c[0] for c in client.calls], ["display"])

    def test_check_alter_never_mutates(self):
        client = self.queue_client()
        obj = copy.deepcopy(QUEUE)
        obj["attributes"]["maxdepth"] = 7000
        result = mq.reconcile(client, [obj], check_mode=True)
        self.assertEqual(result["plans"][0]["action"], "alter")
        self.assertEqual(client.objects[obj["name"]]["maxdepth"], 5000)

    def test_deletion_requires_explicit_authorization_even_in_check(self):
        obj = dict(name=QUEUE["name"], type="qlocal", state="absent")
        for check in (True, False):
            with self.assertRaises(mq.MQError):
                mq.reconcile(self.queue_client(), [obj], check_mode=check)

    def test_delete_is_verified_and_idempotent(self):
        obj = dict(name=QUEUE["name"], type="qlocal", state="absent")
        client = self.queue_client()
        self.assertTrue(mq.reconcile(client, [obj], allow_deletion=True)["changed"])
        self.assertFalse(mq.reconcile(client, [obj], allow_deletion=True)["changed"])
        deletion = next(c for c in client.calls if c[0] == "delete")
        self.assertEqual(deletion[3], {})  # no PURGE or FORCE

    def test_channel_delete_is_qualified_with_discovered_type(self):
        name = "BERGEN.CLIENT"
        client = FakeClient({name: dict(channel=name, chltype="CLNTCONN")})
        result = mq.reconcile(client, [dict(name=name, type="channel", state="absent")],
                              allow_deletion=True)
        self.assertTrue(result["changed"])
        deletion = next(call for call in client.calls if call[0] == "delete")
        self.assertEqual(deletion[3], {"chltable": "clntconn"})

    def test_non_client_channel_delete_uses_qmgr_table(self):
        name = "BERGEN.RECEIVER"
        client = FakeClient({name: dict(channel=name, chltype="RCVR")})
        mq.reconcile(client, [dict(name=name, type="channel", state="absent")],
                     allow_deletion=True)
        deletion = next(call for call in client.calls if call[0] == "delete")
        self.assertEqual(deletion[3], {"chltable": "qmgr"})

    def test_channel_delete_refuses_missing_type_before_mutation(self):
        name = "BERGEN.CLIENT"
        client = FakeClient({name: dict(channel=name)})
        with self.assertRaisesRegex(mq.MQError, "channel type"):
            mq.reconcile(client, [dict(name=name, type="channel", state="absent")],
                         allow_deletion=True)
        self.assertFalse(any(call[0] == "delete" for call in client.calls))

    def test_check_delete_does_not_mutate(self):
        client = self.queue_client()
        obj = dict(name=QUEUE["name"], type="qlocal", state="absent")
        self.assertTrue(mq.reconcile(client, [obj], check_mode=True, allow_deletion=True)["changed"])
        self.assertIn(obj["name"], client.objects)

    def test_wrong_queue_type_is_not_absence(self):
        client = self.queue_client()
        client.objects[QUEUE["name"]]["type"] = "QALIAS"
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [QUEUE])
        self.assertTrue(all(c[0] == "display" for c in client.calls))

    def test_all_inputs_validated_before_network(self):
        client = FakeClient()
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [QUEUE, dict(name="BAD*", type="qlocal")])
        self.assertFalse(client.calls)

    def test_all_discovery_finishes_before_mutation(self):
        client = FakeClient()
        client.fail_on = ("display", "SECOND")
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [QUEUE, dict(name="SECOND", type="qlocal")])
        self.assertTrue(all(c[0] == "display" for c in client.calls))

    def test_mutation_failure_reports_unknown_outcome_and_no_retry(self):
        client = FakeClient()
        client.fail_on = ("define", QUEUE["name"])
        with self.assertRaises(mq.MQError) as caught:
            mq.reconcile(client, [QUEUE])
        self.assertTrue(caught.exception.mutation_attempted)
        self.assertEqual(sum(c[0] == "define" for c in client.calls), 1)

    def test_post_change_drift_fails(self):
        client = self.queue_client()
        client.ignore_updates = True
        obj = copy.deepcopy(QUEUE)
        obj["attributes"]["maxdepth"] = 7000
        with self.assertRaises(mq.MQError) as caught:
            mq.reconcile(client, [obj])
        self.assertEqual(len(caught.exception.applied), 1)

    def test_missing_declared_attribute_fails_closed(self):
        client = self.queue_client()
        del client.objects[QUEUE["name"]]["maxdepth"]
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [QUEUE])

    def test_identity_mismatch_fails(self):
        client = self.queue_client()
        client.objects[QUEUE["name"]]["queue"] = "DIFFERENT"
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [QUEUE])

    def test_queue_types_create(self):
        for typ in ("qlocal", "qremote", "qalias", "qmodel"):
            with self.subTest(typ=typ):
                obj = dict(name="BERGEN.TEST", type=typ)
                client = FakeClient()
                self.assertTrue(mq.reconcile(client, [obj])["changed"])
                self.assertFalse(mq.reconcile(client, [obj])["changed"])

    def test_channels_create_and_alter_with_type_qualifier(self):
        for typ in mq.CHANNEL_TYPES:
            obj = dict(name="BERGEN.TEST", type="channel", attributes=dict(chltype=typ, conname="host.example(1414)", hbint=30))
            client = FakeClient()
            self.assertTrue(mq.reconcile(client, [obj])["changed"])
            self.assertFalse(mq.reconcile(client, [obj])["changed"])
            obj["attributes"]["hbint"] = 60
            plan = mq.reconcile(client, [obj])["plans"][0]
            self.assertEqual(plan["parameters"], dict(hbint=60, chltype=typ))

    def test_channel_type_conversion_fails(self):
        obj = dict(name="BERGEN.TEST", type="channel", attributes=dict(chltype="svrconn"))
        client = FakeClient()
        mq.reconcile(client, [obj])
        obj["attributes"]["chltype"] = "rcvr"
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [obj])

    def test_topic_and_namelist_roundtrip(self):
        for obj in [dict(name="BERGEN.TOPIC", type="topic", attributes=dict(topicstr="bergen/events", pub="enabled")),
                    dict(name="BERGEN.NAMES", type="namelist", attributes=dict(names=["A", "b"], nltype="queue"))]:
            client = FakeClient()
            self.assertTrue(mq.reconcile(client, [obj])["changed"])
            self.assertFalse(mq.reconcile(client, [obj])["changed"])

    def test_topic_string_conversion_fails(self):
        obj = dict(name="BERGEN.TOPIC", type="topic", attributes=dict(topicstr="bergen/events"))
        client = FakeClient()
        mq.reconcile(client, [obj])
        obj["attributes"]["topicstr"] = "different"
        with self.assertRaises(mq.MQError):
            mq.reconcile(client, [obj])

    def test_create_requirements_checked_before_any_mutation(self):
        for obj in [dict(name="BERGEN.TOPIC", type="topic"),
                    dict(name="BERGEN.CHANNEL", type="channel", attributes=dict(chltype="sdr"))]:
            client = FakeClient()
            with self.assertRaises(mq.MQError):
                mq.reconcile(client, [QUEUE, obj])
            self.assertTrue(all(c[0] == "display" for c in client.calls))


class SafetyTests(unittest.TestCase):
    def test_invalid_declarations(self):
        cases = [[], {}, [dict(name="SYSTEM.DEFAULT.LOCAL.QUEUE", type="qlocal")],
                 [dict(name="AMQ.TEST", type="qlocal")], [dict(name="BAD;DELETE", type="qlocal")],
                 [dict(name="TEST", type="chlauth")], [dict(name="TEST", type="authrec")],
                 [dict(name="TEST", type="qmgr")], [dict(name="TEST", type="qlocal", state="running")],
                 [dict(name="TEST", type="qlocal", attributes=dict(replace="yes"))],
                 [dict(name="TEST", type="qlocal", attributes=dict(maxdepth=True))],
                 [dict(name="TEST", type="qlocal", attributes=dict(maxdepth="5000"))],
                 [dict(name="TEST", type="qlocal", attributes=dict(defpsist=True))],
                 [dict(name="TEST", type="qlocal", attributes=dict(defpsist="asparent"))],
                 [dict(name="TEST", type="qlocal", attributes=dict(put="banana"))],
                 [dict(name="TEST", type="qlocal", attributes=dict(descr="a\nb"))],
                 [dict(name="TEST", type="channel")],
                 [dict(name="TEST", type="namelist", attributes=dict(names=["A*"]))],
                 [dict(name="TEST", type="qlocal"), dict(name="TEST", type="qalias")]]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(mq.MQError):
                mq.validate_objects(case)

    def test_response_errors_fail_closed(self):
        for data in [{}, {"commandResponse": []}, {"commandResponse": [{}]},
                     dict(commandResponse=[dict(completionCode=0, reasonCode=0)]),
                     dict(commandResponse=[dict(completionCode=2, reasonCode=2035)], overallCompletionCode=2, overallReasonCode=3008),
                     dict(commandResponse=[dict(completionCode=1, reasonCode=0)]),
                     dict(commandResponse=[dict(completionCode=0, reasonCode=0)], overallCompletionCode=2, overallReasonCode=3008),
                     dict(commandResponse=[dict(completionCode=2, reasonCode=2085), dict(completionCode=2, reasonCode=2035)])]:
            with self.subTest(data=data), self.assertRaises(mq.MQError):
                mq.responses(data, allow_missing=True)

    def test_unknown_object_only_allowed_for_discovery(self):
        self.assertEqual(mq.responses(missing(), allow_missing=True), [])
        with self.assertRaises(mq.MQError):
            mq.responses(missing())

    def test_endpoint_restrictions(self):
        for endpoint in ["http://host/ibmmq/rest/v3", "https://u:p@host/ibmmq/rest/v3",
                         "https://host/other", "https://host/ibmmq/rest/v3?token=x", "https://host/ibmmq/rest/v3#x"]:
            with self.assertRaises(mq.MQError):
                mq.RestClient(endpoint, "QM1", "test", "dummy")

    def test_redirect_is_refused(self):
        with self.assertRaises(mq.MQError):
            mq.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other")


if __name__ == "__main__":
    unittest.main()
