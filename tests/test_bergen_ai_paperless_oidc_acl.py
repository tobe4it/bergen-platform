"""Offline security contracts for sampled OIDC-linked Paperless Guardian/DRF ACLs."""
import ast
import importlib.util
import os
import stat
import tempfile
import hashlib
import hmac
import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "ansible/files/paperless/audit_oidc_acl_sample.py"
PLAY = ROOT / "ansible/playbooks/audit-bergen-ai-paperless-oidc-acl-sample-readonly.yml"


def fixture_functions():
    tree = ast.parse(PROBE.read_text())
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name in ("AuditError", "demand", "fingerprint",
                                  "verify_cases", "oidc_provider",
                                  "verify_ai_fingerprints", "bind_users",
                                  "authorize_examples")]
    scope = {"hmac": hmac, "hashlib": hashlib, "re": re,
             "HEX64": re.compile(r"^[0-9a-f]{64}$")}
    states = next(node for node in tree.body
                  if isinstance(node, ast.Assign) and any(
                      isinstance(t, ast.Name) and t.id == "SAFE_ACTOR_STATES"
                      for t in node.targets
                  ))
    scope["SAFE_ACTOR_STATES"] = frozenset(ast.literal_eval(states.value.args[0]))
    exec(compile(ast.Module(body=selected, type_ignores=[]),
                 str(PROBE), "exec"), scope)
    return scope


LIB = fixture_functions()
KEY = "S" * 64


def email_h(s):
    return LIB["fingerprint"](KEY, s)


def case_matrix():
    return [
        {"username": name, "document_id": doc, "allow": granted}
        for doc, permitted in (
            (1001, (True, False)),
            (1002, (False, True)),
            (1003, (True, True)),
            (1004, (False, False)),
        )
        for name, granted in zip(("parent_a", "parent_b"), permitted)
    ]


def ai_rows():
    return {
        "AUDIT": "READ_ONLY", "SYSTEM": "BERGEN_AI", "COUNT": 2,
        "ACCOUNTS": [
            {"email": email_h("a@example.invalid"),
             "subject": email_h("subject-a"), "role": "USER"},
            {"email": email_h("b@example.invalid"),
             "subject": email_h("subject-b"), "role": "USER"},
        ]
    }


class FakeUser:
    def __init__(self, name, email, *, is_active=True, is_superuser=False,
                 is_staff=False):
        self.username = name
        self.email = email
        self.is_active = is_active
        self.is_superuser = is_superuser
        self.is_staff = is_staff


class FakeLink:
    def __init__(self, user, uid="", extra_data=None):
        self.user = user
        self.uid = uid
        self.extra_data = extra_data or {}


class FakeManager:
    def __init__(self, links):
        self.links = links
        self.selected_provider = None

    def filter(self, provider):
        self.selected_provider = provider
        return self

    def select_related(self, _):
        return self

    def order_by(self, _):
        return self

    def __getitem__(self, _):
        return self.links


class FakeSocialAccount:
    objects = None


def load_matrix_builder():
    location = ROOT / "ansible/scripts/prepare_paperless_oidc_acl_matrix.py"
    spec = importlib.util.spec_from_file_location("private_matrix_builder", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATRIX = load_matrix_builder()


class Tests(unittest.TestCase):
    def test_operator_matrix_is_policy_based_and_ignored_by_main_repo(self):
        cases = MATRIX.build_cases(
            ["real_a", "real_b"], [1001, 1002, 1003, 1004]
        )
        expected = (
            (True, False), (False, True), (True, True), (True, True)
        )
        self.assertEqual(len(cases), 8)
        for idx, pair in enumerate(expected):
            self.assertEqual(cases[idx * 2]["allow"], pair[0])
            self.assertEqual(cases[idx * 2 + 1]["allow"], pair[1])
        self.assertEqual(LIB["verify_cases"](cases)[2:], (6, 2))
        self.assertIn(
            "ansible/vars/paperless*.local.yml",
            (ROOT / ".gitignore").read_text()
        )
        self.assertEqual(MATRIX.ALLOWED_FILE, "paperless-ai-acl.local.yml")

    def test_no_private_b_profile_three_documents_and_limited_coverage(self):
        cases = MATRIX.build_cases(["a", "b"], [41, 42, 43], "no-private-b")
        self.assertEqual(len(cases), 6)
        self.assertEqual([c["allow"] for c in cases],
                         [True, False, True, True, True, True])
        actors, docs, allowed, denied = LIB["verify_cases"](cases, "no-private-b")
        self.assertEqual(actors, {"a", "b"})
        self.assertEqual(docs, {41, 42, 43})
        self.assertEqual((allowed, denied), (5, 1))
        rendered = MATRIX.render_matrix(cases, "no-private-b")
        self.assertIn("paperless_oidc_acl_profile: no-private-b", rendered)
        self.assertEqual(rendered.count("document_id:"), 6)

    def test_partial_coverage_cannot_be_mislabeled_symmetric(self):
        cases = MATRIX.build_cases(["a", "b"], [41, 42, 43], "no-private-b")
        with self.assertRaises(LIB["AuditError"]):
            LIB["verify_cases"](cases, "balanced")
        with self.assertRaises(LIB["AuditError"]):
            LIB["verify_cases"]([dict(c, allow=True) for c in cases],
                                "no-private-b")
        self.assertIn("ONE_ACTOR_UNTESTED", PLAY.read_text())
        self.assertIn("OIDC_LINKED_PAPERLESS_ACL_SAMPLE_LIMITED",
                      PROBE.read_text())

    def test_operator_matrix_refuses_duplicate_and_invalid_values(self):
        valid_users = ["alpha", "beta"]
        docs = [1001, 1002, 1003, 1004]
        for users, documents in (
            (["same", "same"], docs),
            (["", "beta"], docs),
            (["alpha", "user\ninjected"], docs),
            (valid_users, [1, 1, 3, 4]),
            (valid_users, [1, 2, True, 4]),
            (valid_users, [1, 2, 3, -4]),
        ):
            with self.subTest(users=users, documents=documents):
                with self.assertRaises(MATRIX.InvalidMatrix):
                    MATRIX.build_cases(users, documents)

    def test_private_matrix_file_is_0600_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "vars"
            parent.mkdir()
            path = parent / MATRIX.ALLOWED_FILE
            content = MATRIX.render_matrix(
                MATRIX.build_cases(["alpha", "beta"], [1001, 1002, 1003, 1004])
            )
            MATRIX.write_private(path, content)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_text(), content)
            with self.assertRaises(MATRIX.InvalidMatrix):
                MATRIX.write_private(path, "altered")
            self.assertEqual(path.read_text(), content)
            self.assertIn("allow: false", content)
            self.assertIn("allow: true", content)
            self.assertIn("paperless_oidc_acl_audit_approved: true", content)

    def test_policy_builder_never_reads_live_acl_or_secrets(self):
        source = (
            ROOT / "ansible/scripts/prepare_paperless_oidc_acl_matrix.py"
        ).read_text()
        self.assertNotIn("import requests", source)
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("import django", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("APIClient", source)
        self.assertIn("os.O_EXCL", source)
        self.assertIn("os.O_NOFOLLOW", source)

    def test_8_cases_cover_two_accounts_with_allow_and_deny(self):
        users, docs, allowed, denied = LIB["verify_cases"](case_matrix())
        self.assertEqual(users, {"parent_a", "parent_b"})
        self.assertEqual(docs, {1001, 1002, 1003, 1004})
        self.assertEqual((allowed, denied), (4, 4))

    def test_invalid_incomplete_duplicate_or_all_allowed_matrix_fails(self):
        valid = case_matrix()
        violations = [
            valid[:-1],
            valid[:-1] + [valid[0]],
            [dict(c, allow=True) for c in valid],
            [dict(c, username="single_actor") for c in valid],
            [dict(c, document_id=1) for c in valid],
            [dict(c, document_id=True) if i == 1 else c
             for i, c in enumerate(valid)],
        ]
        for v in violations:
            with self.subTest(v=v), self.assertRaises(LIB["AuditError"]):
                LIB["verify_cases"](v)

    def test_only_exact_configured_oidc_app_is_accepted(self):
        self.assertEqual(
            LIB["oidc_provider"]({"openid_connect": {
                "APPS": [{"provider_id": "synology-synthetic"}]}}),
            "synology-synthetic",
        )
        for candidate in (
            {},
            {"google": {"APPS": [{"provider_id": "google"}]}},
            {"openid_connect": {"APPS": [
                {"provider_id": "provider-A"}, {"provider_id": "provider-B"}
            ]}},
            {"openid_connect": {"APPS": [{"provider_id": "malformed name"}]}},
        ):
            with self.subTest(config=candidate), self.assertRaises(LIB["AuditError"]):
                LIB["oidc_provider"](candidate)

    def test_matching_oidc_subject_must_be_bound_to_selected_paperless_user(self):
        manager = FakeManager([
            FakeLink(FakeUser("parent_a", "a@example.invalid"), uid="subject-a"),
            FakeLink(FakeUser("parent_b", "b@example.invalid"),
                     extra_data={"sub": "subject-b"}),
        ])
        FakeSocialAccount.objects = manager
        LIB["bind_users"].__globals__["SocialAccount"] = FakeSocialAccount
        LIB["bind_users"].__globals__["User"] = FakeUser
        actors = LIB["bind_users"]({"parent_a", "parent_b"}, ai_rows(),
                                   KEY, "synology-synthetic")
        self.assertEqual(set(actors), {"parent_a", "parent_b"})
        self.assertEqual(manager.selected_provider, "synology-synthetic")
        self.assertNotIn("a@example.invalid", json.dumps({
            "matched": len(actors), "provider": manager.selected_provider
        }))

    def test_wrong_paperless_username_reports_only_actor_alias(self):
        # Paperless username may be a local short name, while the user's
        # Synology sign-in value is a realm-qualified identifier.
        FakeSocialAccount.objects = FakeManager([
            FakeLink(FakeUser("parent_a", "a@example.invalid"), uid="subject-a"),
            FakeLink(FakeUser("parent_b", "b@example.invalid"), uid="subject-b"),
        ])
        LIB["bind_users"].__globals__["SocialAccount"] = FakeSocialAccount
        LIB["bind_users"].__globals__["User"] = FakeUser
        with self.assertRaises(LIB["AuditError"]) as failure:
            LIB["bind_users"](
                {"parent_a", "parent_b@bergen.invalid"},
                ai_rows(), KEY, "synology-synthetic",
                ["parent_a", "parent_b@bergen.invalid"]
            )
        self.assertEqual(str(failure.exception), "IDENTITY_UNLINKED")
        self.assertEqual(failure.exception.actor_states, {
            "A": "MATCHED", "B": "NO_CONFIGURED_OIDC_LINK"
        })
        self.assertNotIn("parent_b@bergen.invalid",
                         str(failure.exception.actor_states))
        play = PLAY.read_text()
        self.assertIn("MATRIX_ACCOUNT_A_LINK", play)
        self.assertIn("MATRIX_ACCOUNT_B_LINK", play)

    def test_wrong_oidc_subject_is_classified_without_identifiers(self):
        FakeSocialAccount.objects = FakeManager([
            FakeLink(FakeUser("parent_a", "a@example.invalid"), uid="wrong-sub"),
            FakeLink(FakeUser("parent_b", "b@example.invalid"), uid="subject-b"),
        ])
        LIB["bind_users"].__globals__["SocialAccount"] = FakeSocialAccount
        LIB["bind_users"].__globals__["User"] = FakeUser
        with self.assertRaises(LIB["AuditError"]) as failure:
            LIB["bind_users"](
                {"parent_a", "parent_b"}, ai_rows(), KEY,
                "synology-synthetic", ["parent_a", "parent_b"]
            )
        self.assertEqual(failure.exception.actor_states, {
            "A": "SUBJECT_MISMATCH", "B": "MATCHED"
        })

    def test_same_email_wrong_sub_cannot_bind(self):
        FakeSocialAccount.objects = FakeManager([
            FakeLink(FakeUser("parent_a", "a@example.invalid"),
                     uid="another-subject"),
            FakeLink(FakeUser("parent_b", "b@example.invalid"), uid="subject-b")
        ])
        LIB["bind_users"].__globals__["SocialAccount"] = FakeSocialAccount
        LIB["bind_users"].__globals__["User"] = FakeUser
        with self.assertRaises(LIB["AuditError"]):
            LIB["bind_users"]({"parent_a", "parent_b"}, ai_rows(),
                              KEY, "synology-synthetic")

    def test_disabled_or_superuser_paperless_account_cannot_bind(self):
        for options in ({"is_active": False}, {"is_superuser": True},
                        {"is_staff": True}):
            with self.subTest(options=options):
                FakeSocialAccount.objects = FakeManager([
                    FakeLink(FakeUser("parent_a", "a@example.invalid", **options),
                             uid="subject-a"),
                    FakeLink(FakeUser("parent_b", "b@example.invalid"),
                             uid="subject-b"),
                ])
                LIB["bind_users"].__globals__["SocialAccount"] = FakeSocialAccount
                LIB["bind_users"].__globals__["User"] = FakeUser
                with self.assertRaisesRegex(LIB["AuditError"], "IDENTITY_UNLINKED") as error:
                    LIB["bind_users"]({"parent_a", "parent_b"}, ai_rows(),
                                      KEY, "synology-synthetic",
                                      ["parent_a", "parent_b"])
                self.assertEqual(error.exception.actor_states, {
                    "A": "INACTIVE_OR_PRIVILEGED", "B": "MATCHED"
                })

    def test_reused_subject_or_duplicate_socialaccount_fails_closed(self):
        FakeSocialAccount.objects = FakeManager([
            FakeLink(FakeUser("parent_a", "a@example.invalid"), uid="subject-a"),
            FakeLink(FakeUser("parent_a", "a@example.invalid"), uid="subject-a"),
            FakeLink(FakeUser("parent_b", "b@example.invalid"), uid="subject-b"),
        ])
        LIB["bind_users"].__globals__["SocialAccount"] = FakeSocialAccount
        LIB["bind_users"].__globals__["User"] = FakeUser
        with self.assertRaises(LIB["AuditError"]):
            LIB["bind_users"]({"parent_a", "parent_b"}, ai_rows(),
                              KEY, "synology-synthetic")

    def test_read_only_play_composes_approved_identity_audit(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(
            plays[0]["import_playbook"],
            "audit-bergen-ai-paperless-oidc-identity-readonly.yml",
        )
        self.assertEqual(plays[1]["hosts"], "localhost")
        self.assertNotIn("connection", plays[1])
        tasks = plays[1]["tasks"]
        allowed = {"ansible.builtin.command", "ansible.builtin.assert",
                   "ansible.builtin.set_fact", "ansible.builtin.debug"}
        for task in tasks:
            modules = [k for k in task if k.startswith("ansible.builtin.")]
            self.assertEqual(len(modules), 1)
            self.assertIn(modules[0], allowed)
            if modules[0] in ("ansible.builtin.command", "ansible.builtin.set_fact"):
                self.assertIs(task.get("no_log"), True)
                self.assertFalse(task.get("changed_when", False))
        for name in (
            "Require matching OIDC identities and independent reviewed evidence matrix",
            "Read effective Paperless Guardian and DRF decisions for verified identity-linked sample",
            "Fail closed on any denied or incomplete ACL decision",
        ):
            self.assertTrue(any(task.get("name") == name for task in tasks))
        doc = PROBE.read_text()
        self.assertIn('permitted_document_ids(', doc)
        self.assertIn('perm="view_document"', doc)
        self.assertIn("force_authenticate(user=user)", doc)
        self.assertIn("SocialAccount.objects.filter(provider=provider)", doc)
        self.assertIn("RESULT", doc.replace("FRAME", "RESULT"))
        for bad in (".save(", ".delete(", "assign_perm(", "change_document",
                    "import requests", "Authorization: Bearer"):
            self.assertNotIn(bad, doc)

    def test_never_report_document_id_username_or_subject(self):
        text = PROBE.read_text()
        start = text.index('        print(FRAME + json.dumps({')
        end = text.index('        }, sort_keys=True))', start)
        summary = text[start:end]
        for private in ('username', 'document_id', 'email', '"sub"', 'uid',
                        'link.user', 'doc_id'):
            self.assertNotIn(private, summary)


if __name__ == "__main__":
    unittest.main()
