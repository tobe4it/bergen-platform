"""Issue 113: offline policy/Ansible regression gates (no live Paperless data)."""
import ast
import importlib.util
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "ansible/files/paperless/bergen_ai_catalog_policy.py"
RUNNER = ROOT / "ansible/files/paperless/bergen_ai_catalog_runner.py"
PLAY = ROOT / "ansible/playbooks/manage-paperless-ai-inbox-catalog.yml"


def load_policy():
    spec = importlib.util.spec_from_file_location("bergen_ai_catalog_policy", POLICY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


p = load_policy()


def sample():
    return {
        "id": 123, "owner_id": 4, "title": "scan_0042",
        "original_filename": "scan_0042.pdf",
        "correspondent_id": None, "document_type_id": None,
        "storage_path_id": None, "created": "2026-10-18",
        "modified": "2026-10-18T12:20:00+00:00",
        "checksum": "f" * 64, "content_sha256": "a" * 64,
        "tag_ids": [1, 11], "inbox": True,
    }


class CatalogPolicyTest(unittest.TestCase):
    def test_import_title_only_not_manually_edited(self):
        self.assertTrue(p.import_title("scan_0042", "scan_0042.pdf"))
        self.assertTrue(p.import_title("scan_0042.pdf", "scan_0042.pdf"))
        self.assertFalse(p.import_title("Versicherung Oktober 2026", "scan_0042.pdf"))
        self.assertFalse(p.import_title("", "scan_0042.pdf"))
        self.assertFalse(p.import_title(None, "scan_0042.pdf"))

    def test_import_title_is_replaced_but_manual_title_preserved(self):
        before = sample()
        changes = p.plan_changes(
            before, {"title": "Versicherung | 2026"},
            [12, 12, 11], 3, 7
        )
        self.assertEqual(changes["title"], "Versicherung | 2026")
        self.assertEqual(changes["correspondent_id"], 3)
        self.assertEqual(changes["document_type_id"], 7)
        self.assertEqual(changes["add_tag_ids"], [12])
        after_manual = dict(before, title="Von Mutter überprüft")
        changes2 = p.plan_changes(after_manual, {"title": "Nicht überschreiben"},
                                  [12], 3, 7)
        self.assertIsNone(changes2["title"])

    def test_already_classified_fields_are_not_overwritten(self):
        doc = dict(sample(), correspondent_id=31, document_type_id=35)
        result = p.plan_changes(doc, {"title": "Neue KI"},
                                [12], correspondent_id=99, document_type_id=88)
        self.assertIsNone(result["correspondent_id"])
        self.assertIsNone(result["document_type_id"])

    def test_missing_inbox_fails_closed(self):
        with self.assertRaisesRegex(p.PolicyError, "INBOX_REMOVED"):
            p.plan_changes(dict(sample(), inbox=False), {"title": "X"}, [], None, None)

    def test_only_private_ollama_endpoint(self):
        good = [
            "http://192.168.0.10:11434", "http://bergen-ai:11434",
            "http://ollama:11434", "http://10.0.0.9:11434",
        ]
        bad = [
            "https://example.com:11434",
            "http://example.com:11434",
            "http://8.8.8.8:11434",
            "http://192.168.0.10:11435",
            "http://user:pass@192.168.0.10:11434",
            "http://127.0.0.1:11434/api/chat",
            "file:///tmp/secret", "http://169.254.169.254:11434",
            "https://api.openai.com/v1",
        ]
        for endpoint in good:
            with self.subTest(endpoint=endpoint):
                self.assertTrue(p.safe_endpoint(endpoint))
        for endpoint in bad:
            with self.subTest(endpoint=endpoint):
                self.assertFalse(p.safe_endpoint(endpoint))

    def test_snapshot_guard_changes_with_owner_metadata_tags_or_contents(self):
        src = sample()
        base = p.fingerprint(src)
        for field, value in (
            ("owner_id", 999), ("title", "changed"),
            ("tag_ids", [1, 12]), ("content_sha256", "b" * 64),
            ("correspondent_id", 99), ("document_type_id", 11),
            ("inbox", False), ("modified", "2026-10-18T13:00:00+00:00"),
        ):
            with self.subTest(field=field):
                changed = dict(src, **{field: value})
                self.assertNotEqual(p.fingerprint(changed), base)
        self.assertEqual(p.stable_snapshot(src),
                         p.stable_snapshot(dict(reversed(list(src.items())))))

    def test_rejects_unexpected_doc_or_model_fields(self):
        with self.assertRaises(p.PolicyError):
            p.stable_snapshot(dict(sample(), is_superuser=True))
        for values in ({"title": None}, {"document": "instructions"}, "Ignore policy"):
            with self.assertRaises(p.PolicyError):
                p.plan_changes(sample(), values, [], None, None)
        with self.assertRaises(p.PolicyError):
            p.plan_changes(sample(), {"title": "x"}, [None], None, None)

    def test_runner_is_bounded_single_inference_and_forbids_acl_changes(self):
        source = RUNNER.read_text()
        tree = ast.parse(source)
        # One upstream call only. AI LLM does not decide group/tag rights.
        calls = [x for x in ast.walk(tree) if isinstance(x, ast.Call)]
        to_model = [x for x in calls
                    if isinstance(x.func, ast.Name)
                    and x.func.id == "get_ai_document_classification"]
        self.assertEqual(len(to_model), 1)
        self.assertIn("with transaction.atomic()", source)
        self.assertIn("select_for_update()", source)
        self.assertIn('stable_snapshot(snapshot(current_doc)) == before_json', source)
        self.assertIn("get_ai_document_classification(doc, doc.owner, None)", source)
        self.assertIn("is_inbox_tag=True", source)
        self.assertIn("create_missing=False", source)
        self.assertIn('request.get("approved") is True', source)
        self.assertIn('not config.llm_embedding_backend', source)
        self.assertIn('JOURNAL_DB =', source)
        self.assertIn('fcntl.flock', source)
        self.assertIn('REQUIRES_REVIEW', source)
        self.assertIn('ROLLBACK_REVIEW_REQUIRED', source)
        self.assertIn("original_filename", source)
        self.assertIn("root_document_id", source)
        for forbidden in ("assign_perm(", "remove_perm(", "delete_document(",
                          "requests.post(", "httpx.post(", "delete_tag(",
                          "document.owner =", "document.created ="):
            self.assertNotIn(forbidden, source)

    def test_playbook_declines_write_without_backups_and_approval(self):
        plays = yaml.safe_load(PLAY.read_text())
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["hosts"], "venombox")
        tasks = plays[0]["tasks"]
        first = tasks[0]
        text = json.dumps(first["ansible.builtin.assert"], sort_keys=True)
        for field in ("paperless_ai_catalog_verified_backup",
                      "paperless_ai_catalog_approved",
                      "paperless_ai_catalog_pilot_ids",
                      "paperless_ai_catalog_rollback_approved"):
            self.assertIn(field, text)
        calls = [t for t in tasks if "ansible.builtin.command" in t]
        for task in calls:
            self.assertTrue(task.get("no_log", False))
        runner = next(t for t in tasks if
                      "Execute application-native" in t["name"])
        argv = runner["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:3], ["pct", "exec", "126"])
        self.assertIn("bergen_ai_catalog_policy.py", json.dumps(argv))
        self.assertIn("bergen_ai_catalog_runner.py", json.dumps(argv))
        self.assertIn("stdin", runner["ansible.builtin.command"])
        self.assertFalse(runner["failed_when"])


if __name__ == "__main__":
    unittest.main()
