"""Offline no-production-write tests for gated document 15 journal publication."""
import importlib.util
import io
import json
import os
import pathlib
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "ansible/files/paperless"
sys.path.insert(0, str(SCRIPTS))


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = load("deleted_by_user_15_decision_journal.py", "journal_15_test_schema")
publisher = load("publish_deleted_by_user_15_journal.py", "journal_15_test_publisher")
plan = load("plan_deleted_by_user_15_journal_target.py", "journal_15_test_plan")
DIGEST = "bb2a4b44d6d34b8aad29716129c16cdcf6fd2e00fc45a1c6990de8f23086ed7c"
RECEIVER = "Privat/thomas/Gebuehren--nas-" + DIGEST + ".pdf"
NAS = {
    "schema_version": 1,
    "sender_receipt": "adbbbd6b2ca9b6189da559a5e4d303e03eed2cb2403efaf14d343d02fd042b53.json",
    "scope": "Privat/thomas", "source": "Gebuehren.pdf",
    "receiver_source": RECEIVER, "sha256": DIGEST,
    "sender_status": "SENT", "nas_original_absent": True,
}
DELETED = {
    "schema_version": 1,
    "bridge_receipt": "7a92b91deb7b2e8e35f9f710.json",
    "document_id": 15, "receiver_source": RECEIVER,
    "sha256": DIGEST, "proposed_status": "DELETED_IN_PAPERLESS",
    "live_document_absent": True, "original_filename_absent": True,
}


def request(nas=None, deleted=None):
    return {
        "nas": json.dumps(NAS if nas is None else nas) + "\nNO_FILES_CHANGED",
        "deleted": json.dumps(DELETED if deleted is None else deleted),
        "schema_source": "#!/usr/bin/env python3\nschema placeholder",
        "store_source": "#!/usr/bin/env python3\nstore placeholder",
        "plan_source": "#!/usr/bin/env python3\nplan placeholder",
    }


class Document15JournalPublisherTests(unittest.TestCase):
    def test_exact_identity_is_not_document_26(self):
        self.assertEqual(publisher.EXPECTED_EVENT, schema.EXPECTED_EVENT)
        self.assertEqual(publisher.EXPECTED_RECORD_SHA, schema.EXPECTED_PAYLOAD_HASH)
        self.assertNotEqual(publisher.EXPECTED_EVENT,
                            "f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26")

    def test_publish_simulation_without_disk_writes(self):
        events = []
        record = schema.build(NAS, DELETED)

        def check_directory(path):
            events.append("check_directory")
            return os.open(os.devnull, os.O_RDONLY)

        def publish_once(path, candidate):
            events.append("publish_once")
            self.assertEqual(candidate, record)
            self.assertEqual(path, publisher.DIRECTORY)
            return path / (schema.EXPECTED_EVENT + ".json"), True

        def open_private(path):
            events.append("open_private")
            return os.open(os.devnull, os.O_RDONLY)

        def verify_existing(fd, name, payload):
            events.append("verify_existing")
            self.assertEqual(name, schema.EXPECTED_EVENT + ".json")
            self.assertEqual(payload, schema.canonical(record))

        fake_store = types.SimpleNamespace(
            publish_once=publish_once,
            _open_private_directory=open_private,
            _existing_matches=verify_existing,
        )
        fake_plan = types.SimpleNamespace(
            validate=plan.validate, check_directory=check_directory)
        modules = {
            "deleted_by_user_decision_journal": schema,
            "deleted_by_user_decision_store": fake_store,
            "plan_deleted_by_user_journal_target": fake_plan,
        }
        with patch.object(publisher, "_load_module", side_effect=lambda name, src: modules[name]), \
             patch.object(publisher.os, "geteuid", return_value=997), \
             patch.object(publisher.os, "getegid", return_value=988), \
             patch.object(publisher.pwd, "getpwnam",
                          return_value=types.SimpleNamespace(pw_uid=997, pw_gid=988)), \
             redirect_stdout(io.StringIO()) as output:
            publisher.main(request())
        self.assertEqual(events, ["check_directory", "publish_once",
                                  "open_private", "verify_existing"])
        self.assertIn("JOURNAL_CREATED_AND_VERIFIED", output.getvalue())
        self.assertIn("NO_RECEIPTS_CHANGED", output.getvalue())
        self.assertIn("NO_ARCHIVE_AUTHORIZATION", output.getvalue())

    def test_rejects_wrong_evidence_without_store_call(self):
        fake_store = types.SimpleNamespace(
            publish_once=lambda *args: self.fail("store must not be called"))
        modules = {
            "deleted_by_user_decision_journal": schema,
            "deleted_by_user_decision_store": fake_store,
            "plan_deleted_by_user_journal_target": plan,
        }
        bad = request(deleted=dict(DELETED, document_id=26))
        with patch.object(publisher, "_load_module", side_effect=lambda name, src: modules[name]), \
             patch.object(publisher.os, "geteuid", return_value=997), \
             patch.object(publisher.os, "getegid", return_value=988), \
             patch.object(publisher.pwd, "getpwnam",
                          return_value=types.SimpleNamespace(pw_uid=997, pw_gid=988)):
            with self.assertRaisesRegex(ValueError, "USER_DELETION_LIVE_EVIDENCE_MISMATCH"):
                publisher.main(bad)

    def test_wrong_user_blocks_before_loading_code(self):
        with patch.object(publisher.os, "geteuid", return_value=0), \
             patch.object(publisher, "_load_module",
                          side_effect=AssertionError("module must not load")):
            with self.assertRaisesRegex(RuntimeError, "RESTRICTED_INGEST_IDENTITY_REQUIRED"):
                publisher.main(request())

    def test_rejects_wrong_request_fields(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_JOURNAL_PUBLICATION_REQUEST"):
            publisher.main({"document_id": 26})

    def test_cli_requires_explicit_apply(self):
        source = (SCRIPTS / "publish_deleted_by_user_15_journal.py").read_text()
        self.assertIn('if sys.argv != [sys.argv[0], "--apply"]:', source)
        self.assertIn("EXPLICIT_APPLY_ARGUMENT_REQUIRED", source)
        self.assertIn("plan.validate(record) != payload", source)
        self.assertIn("store.publish_once(DIRECTORY, record)", source)

    def test_gated_playbook_requires_explicit_document15_approval_first(self):
        text = (ROOT / "ansible/playbooks/publish-paperless-deleted-by-user-15-journal.yml").read_text()
        self.assertIn("paperless_user_deletion_15_journal_apply_approved | default(false) | bool", text)
        self.assertIn("DOCUMENT_15_JOURNAL_WRITE_NOT_APPROVED", text)
        self.assertLess(text.index("DOCUMENT_15_JOURNAL_WRITE_NOT_APPROVED"),
                        text.index("Verify expected Paperless LXC configuration"))
        self.assertIn("publish_deleted_by_user_15_journal.py", text)
        self.assertNotIn("publish_deleted_by_user_journal.py", text)
        self.assertIn("deleted_15_paperless_final.stdout == deleted_15_paperless.stdout", text)
        self.assertIn("deleted_15_nas_final.stdout == deleted_15_nas.stdout", text)
        self.assertIn("deleted_15_prior_journal_after.stdout == deleted_15_prior_journal.stdout", text)
        self.assertIn("NO_ARCHIVE_AUTHORIZATION", text)
        self.assertIn("changed_when: \"'JOURNAL_CREATED_AND_VERIFIED'", text)

    def test_existing_document26_writer_unchanged_and_not_invoked(self):
        old = (SCRIPTS / "publish_deleted_by_user_journal.py").read_text()
        new = (SCRIPTS / "publish_deleted_by_user_15_journal.py").read_text()
        self.assertIn("f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26", old)
        self.assertNotIn("f4ec236e1eec5af84a73a3fa528c7bd2afa41307c4319a2ac8b26643dbdb0e26", new)


if __name__ == "__main__":
    unittest.main()
