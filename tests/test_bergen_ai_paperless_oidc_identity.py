"""No-live-service security tests for sealed Paperless/Bergen-AI identity JOIN."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
AI_FILE = ROOT / "ansible/files/bergen_ai/audit_oidc_identity_binding_v0102.py"
PAPERLESS_FILE = ROOT / "ansible/files/paperless/audit_oidc_identity_binding.py"
JOIN_FILE = ROOT / "ansible/files/bergen_ai/compare_oidc_subject_fingerprints.py"
PLAY_FILE = ROOT / "ansible/playbooks/audit-bergen-ai-paperless-oidc-identity-readonly.yml"


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AI = load_file(AI_FILE, "oidc_bridge_ai")
JOIN = load_file(JOIN_FILE, "oidc_bridge_join")
KEY = "K" * 64


def ai_row(email, sub, role="USER"):
    return {"email": AI.seal(KEY, email), "subject": AI.seal(KEY, sub), "role": role}


def p_row(email, sub=None, uid=None, active=True):
    return {"email": AI.seal(KEY, email),
            "sub": AI.seal(KEY, sub) if sub else None,
            "uid": AI.seal(KEY, uid) if uid else None,
            "active": active, "staff": False}


def inputs(a, b):
    return (
        {"AUDIT": "READ_ONLY", "SYSTEM": "BERGEN_AI", "ACCOUNTS": a, "COUNT": len(a)},
        {"AUDIT": "READ_ONLY", "SYSTEM": "PAPERLESS", "ACCOUNTS": b, "COUNT": len(b)},
    )


class IdentityBoundaryTests(unittest.TestCase):
    def test_positive_identity_subject_and_email_match(self):
        a, p = inputs(
            [ai_row("parent@example.invalid", "random-subject")],
            [p_row("parent@example.invalid", sub="random-subject", uid="prefixed:random-subject")],
        )
        result = JOIN.compare(a, p)
        self.assertEqual(result["STATUS"], "LINK_CANDIDATES_PRESENT")
        self.assertEqual(result["MATCHED_ACTIVE_EMAIL_AND_SUBJECT"], 1)
        self.assertEqual(result["ISSUER_EQUALITY"], "NOT_PROVEN")
        self.assertEqual(result["LIVE_USER_DELEGATION"], "NOT_PROVEN")
        self.assertEqual(result["PAPERLESS_DOCUMENT_ACL"], "NOT_PROVEN")
        self.assertEqual(result["AUTOMATIC_GROUP_SYNC_SAFE"], "NO")

    def test_normalized_emails_match_without_exposing_them(self):
        self.assertEqual(
            AI.seal(KEY, "parent@example.invalid"),
            AI.seal(KEY, "parent@example.invalid"),
        )
        self.assertNotIn("parent@example.invalid", json.dumps(JOIN.compare(
            *inputs([ai_row("parent@example.invalid", "s")],
                    [p_row("parent@example.invalid", sub="s")]))))

    def test_correct_email_wrong_subject_fails_review(self):
        result = JOIN.compare(*inputs(
            [ai_row("child@example.invalid", "child-sub")],
            [p_row("child@example.invalid", uid="parent-sub")],
        ))
        self.assertEqual(result["SUBJECT_MISMATCH_SAME_EMAIL"], 1)
        self.assertEqual(result["MATCHED_ACTIVE_EMAIL_AND_SUBJECT"], 0)
        self.assertEqual(result["STATUS"], "REQUIRES_IDENTITY_REVIEW")

    def test_same_subject_other_email_requires_review(self):
        result = JOIN.compare(*inputs(
            [ai_row("before@example.invalid", "same-sub")],
            [p_row("after@example.invalid", sub="same-sub")],
        ))
        self.assertEqual(result["SUBJECT_MATCH_EMAIL_DRIFT"], 1)
        self.assertEqual(result["STATUS"], "REQUIRES_IDENTITY_REVIEW")

    def test_disabled_paperless_account_never_counts_as_matched(self):
        result = JOIN.compare(*inputs(
            [ai_row("parent@example.invalid", "s")],
            [p_row("parent@example.invalid", sub="s", active=False)],
        ))
        self.assertEqual(result["INACTIVE_PAPERLESS_IDENTITY"], 1)
        self.assertEqual(result["MATCHED_ACTIVE_EMAIL_AND_SUBJECT"], 0)

    def test_missing_paperless_link(self):
        result = JOIN.compare(*inputs(
            [ai_row("a@example.invalid", "a")], []))
        self.assertEqual(result["PAPERLESS_LINK_MISSING"], 1)

    def test_same_subject_mapped_to_two_paperless_accounts_fails_closed(self):
        with self.assertRaises(JOIN.Unsafe):
            JOIN.compare(*inputs(
                [ai_row("a@example.invalid", "a")],
                [p_row("a@example.invalid", sub="a"),
                 p_row("b@example.invalid", sub="a")]
            ))

    def test_duplicate_email_or_malformed_fingerprint_fails_closed(self):
        same = ai_row("same@example.invalid", "x")
        with self.assertRaises(JOIN.Unsafe):
            JOIN.compare(*inputs([same, same], []))
        bad = dict(same, subject="test")
        with self.assertRaises(JOIN.Unsafe):
            JOIN.compare(*inputs([bad], []))

    def test_hmac_changes_with_ephemeral_key(self):
        self.assertNotEqual(AI.seal(KEY, "subject"), AI.seal("X" * 64, "subject"))
        self.assertNotEqual(AI.seal(KEY, "subject"), AI.seal(KEY, "other-subject"))

    def test_ai_db_inventory_exposes_only_fingerprints_and_is_select_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "webui.db"
            db = sqlite3.connect(file)
            db.execute("CREATE TABLE user (email TEXT, role TEXT, oauth TEXT)")
            db.execute("INSERT INTO user VALUES (?,?,?)", (
                "parent@example.invalid", "user",
                json.dumps({"oidc": {"sub": "separate-provider-sub"}})))
            db.execute("INSERT INTO user VALUES (?,?,?)", (
                "local-admin@example.invalid", "admin", None))
            db.commit()
            before = file.read_bytes()
            data = AI.read_rows(file, KEY, "oidc")
            self.assertEqual(before, file.read_bytes())
            self.assertEqual(len(data), 1)
            self.assertNotIn("parent@example.invalid", json.dumps(data))
            self.assertNotIn("separate-provider-sub", json.dumps(data))
            self.assertEqual(data[0]["role"], "USER")
            db.close()

    def test_json_null_oauth_accounts_are_not_assumed_to_be_corrupt(self):
        # SQLAlchemy Column(JSON) can persist Python None as the literal
        # JSON text "null", alongside true SQLite NULL in older records.
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "webui.db"
            db = sqlite3.connect(file)
            db.execute("CREATE TABLE user (email TEXT, role TEXT, oauth TEXT)")
            db.executemany("INSERT INTO user VALUES (?,?,?)", [
                ("local@example.invalid", "admin", None),
                ("oauth-unlinked@example.invalid", "user", "null"),
                ("oauth-linked@example.invalid", "user",
                 json.dumps({"oidc": {"sub": "signed-oidc-subject"}})),
            ])
            db.commit()
            before = file.read_bytes()
            rows = AI.read_rows(file, KEY, "oidc")
            self.assertEqual(before, file.read_bytes())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["email"], AI.seal(KEY, "oauth-linked@example.invalid"))
            self.assertNotIn("signed-oidc-subject", json.dumps(rows))
            db.close()

    def test_non_null_unsupported_oauth_shapes_still_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "webui.db"
            db = sqlite3.connect(file)
            db.execute("CREATE TABLE user (email TEXT, role TEXT, oauth TEXT)")
            for invalid in ("[]", "true", '"text"', "1", "123.4"):
                with self.subTest(invalid=invalid):
                    db.execute("DELETE FROM user")
                    db.execute("INSERT INTO user VALUES (?,?,?)",
                               ("a@example.invalid", "user", invalid))
                    db.commit()
                    with self.assertRaisesRegex(AI.Unsafe, "^OAUTH_SHAPE_INVALID$"):
                        AI.read_rows(file, KEY, "oidc")
            db.close()

    def test_wrong_provider_is_not_conflated_with_oidc(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "webui.db"
            db = sqlite3.connect(file)
            db.execute("CREATE TABLE user (email TEXT, role TEXT, oauth TEXT)")
            db.execute("INSERT INTO user VALUES (?,?,?)", (
                "somebody@example.invalid", "user",
                json.dumps({"other-provider": {"sub": "same-value"}})))
            db.commit()
            self.assertEqual(AI.read_rows(file, KEY, "oidc"), [])
            db.close()

    def test_failed_closed_diagnostic_is_enumerated_and_never_echoes_private_data(self):
        for code in ("OAUTH_SUBJECT_INVALID", "DATABASE_MISSING",
                     "DB_READ_ERROR", "UNEXPECTED_INTERNAL_ERROR"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                AI.report_failure(code)
            result = json.loads(output.getvalue())
            self.assertEqual(result, {"AUDIT": "FAILED_CLOSED", "CODE": code})

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            AI.report_failure("sensitive-user@example.invalid")
        self.assertEqual(json.loads(output.getvalue())["CODE"],
                         "UNEXPECTED_INTERNAL_ERROR")
        self.assertNotIn("sensitive-user", output.getvalue())

    def test_unexpected_oauth_shape_is_rejected_without_leaking_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "webui.db"
            db = sqlite3.connect(file)
            db.execute("CREATE TABLE user (email TEXT, role TEXT, oauth TEXT)")
            db.execute("INSERT INTO user VALUES (?,?,?)", (
                "secret@example.invalid", "user",
                json.dumps({"oidc": {"not-sub": "token-should-not-leak"}})))
            db.commit()
            with self.assertRaisesRegex(AI.Unsafe, "^OAUTH_SUBJECT_INVALID$"):
                AI.read_rows(file, KEY, "oidc")
            db.close()

    def test_failed_helper_is_stopped_before_any_paperless_access(self):
        tasks = yaml.safe_load(PLAY_FILE.read_text())[0]["tasks"]
        names = [task.get("name") for task in tasks]
        ai_name = "Read sealed Bergen-AI OIDC linkage from SQLite without writes"
        gate_name = "Fail closed before Paperless access if AI identity inventory is invalid"
        paperless_name = "Require existing confined Paperless guest hostname"
        self.assertLess(names.index(ai_name), names.index(gate_name))
        self.assertLess(names.index(gate_name), names.index(paperless_name))
        audit = tasks[names.index(ai_name)]
        self.assertFalse(audit["failed_when"])
        self.assertTrue(audit["no_log"])
        self.assertIn("oidc_identity_ai_raw.rc == 0",
                      str(tasks[names.index(gate_name)]))
        diagnostic_name = "Publish only allowlisted diagnostic category, not private failure data"
        self.assertLess(names.index(diagnostic_name), names.index(gate_name))
        self.assertIn("UNCLASSIFIED_FAILURE",
                      str(tasks[names.index(diagnostic_name)]))

    def test_django_shell_startup_banner_and_one_framed_payload(self):
        # Example default Django 5.2+ shell output; status messages are
        # not JSON and must not be included in the private identity records.
        a, p = inputs(
            [ai_row("parent@example.invalid", "subject")],
            [p_row("parent@example.invalid", sub="subject")],
        )
        raw = (
            "42 objects imported automatically (use -v 2 for details).\n"
            "\n"
            + JOIN.PAPERLESS_FRAME + json.dumps(p, sort_keys=True) + "\n"
        )
        parsed, skipped = JOIN.parse_paperless_stdout(raw)
        self.assertEqual(parsed, p)
        self.assertEqual(skipped, 1)
        result = JOIN.compare(a, parsed)
        self.assertEqual(result["MATCHED_ACTIVE_EMAIL_AND_SUBJECT"], 1)
        self.assertNotIn("parent@example.invalid", json.dumps(result))

    def test_ambiguous_missing_or_malformed_paperless_frame_fails_closed(self):
        p = inputs([], [p_row("parent@example.invalid", sub="abc")])[1]
        marker = JOIN.PAPERLESS_FRAME
        valid = marker + json.dumps(p)
        cases = (
            "42 objects imported automatically (use -v 2 for details).\n",
            valid + "\n" + valid,
            marker + "this is not JSON",
            marker + json.dumps({"AUDIT": "FAILED_CLOSED"}),
        )
        expected = (
            "PAPERLESS_FRAME_MISSING",
            "PAPERLESS_FRAME_DUPLICATE",
            "PAPERLESS_FRAME_JSON_INVALID",
            "PAPERLESS_FRAME_SCHEMA_INVALID",
        )
        for raw, code in zip(cases, expected):
            with self.subTest(code=code), self.assertRaisesRegex(JOIN.Unsafe, "^" + code + "$"):
                JOIN.parse_paperless_stdout(raw)

    def test_paperless_controller_protocol_protects_raw_stdout(self):
        tasks = yaml.safe_load(PLAY_FILE.read_text())[0]["tasks"]
        paperless = next(t for t in tasks if t.get("name") ==
                         "Read sealed Paperless allauth OIDC linkage without changing users")
        args = paperless["ansible.builtin.command"]["argv"]
        self.assertIn("--verbosity=0", args)
        self.assertTrue(paperless["no_log"])
        comparator = next(t for t in tasks if t.get("name") ==
                          "Compare only ephemeral keyed fingerprints on controller")
        self.assertTrue(comparator["no_log"])
        self.assertFalse(comparator["failed_when"])
        self.assertIn("paperless_stdout", str(comparator))
        self.assertNotIn("oidc_identity_paperless_raw.stdout | from_json",
                         PLAY_FILE.read_text())
        self.assertIn("PAPERLESS_OIDC_COMPARE_FAILURE",
                      PLAY_FILE.read_text())
        self.assertIn("Fail closed if Paperless result envelope",
                      PLAY_FILE.read_text())
        self.assertIn("RESULT_FRAME + json.dumps",
                      PAPERLESS_FILE.read_text())

    def test_playbook_has_no_mutations_and_guards_all_secret_outputs(self):
        plays = yaml.safe_load(PLAY_FILE.read_text())
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["hosts"], "localhost")
        # A play-level local connection could redirect delegated remote API
        # checks to bp-controller's own loopback port 3000.
        self.assertNotIn("connection", plays[0])
        tasks_by_name = {task.get("name"): task for task in plays[0]["tasks"]}
        hostname_check = tasks_by_name["Read target hostname from delegated Bergen-AI guest"]
        self.assertEqual(hostname_check["delegate_to"], "{{ oidc_identity_ai_host }}")
        self.assertTrue(hostname_check["no_log"])
        assert_task = tasks_by_name["Refuse AI host identity mismatch before HTTP or identity reads"]
        self.assertTrue(assert_task["no_log"])
        self.assertIn("oidc_identity_ai_hostname.stdout", str(assert_task))
        allowed = {
            "ansible.builtin.assert", "ansible.builtin.uri",
            "ansible.builtin.command", "ansible.builtin.set_fact",
            "ansible.builtin.debug",
        }
        tasks = plays[0]["tasks"]
        for t in tasks:
            modules = [k for k in t if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1)
            self.assertIn(modules[0], allowed)
            if modules[0] in {"ansible.builtin.command", "ansible.builtin.set_fact"}:
                self.assertIs(t["no_log"], True)
                self.assertFalse(t.get("changed_when", False))
            if modules[0] == "ansible.builtin.command":
                self.assertIs(t["check_mode"], False)
        source = AI_FILE.read_text()
        paperless = PAPERLESS_FILE.read_text()
        playtext = PLAY_FILE.read_text()
        self.assertIn("mode=ro", source)
        self.assertIn("PRAGMA query_only=ON", source)
        self.assertIn("SocialAccount.objects.filter", paperless)
        self.assertIn("oidc_identity_ephemeral_hmac", playtext)
        self.assertIn("stdin:", playtext)
        for s in (source, paperless, JOIN_FILE.read_text()):
            self.assertNotIn("Config.upsert", s)
            self.assertNotIn("UPDATE user", s)
            self.assertNotIn(".save(", s)
            self.assertNotIn("print(account", s)
            self.assertNotIn("print(email", s)


if __name__ == "__main__":
    unittest.main()
