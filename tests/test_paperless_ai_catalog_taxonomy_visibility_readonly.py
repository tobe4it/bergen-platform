"""Offline regression for the read-only post-AI taxonomy visibility audit."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ansible/files/paperless/audit_ai_catalog_taxonomy_visibility_readonly.py"
PLAY = ROOT / "ansible/playbooks/audit-paperless-ai-taxonomy-visibility-readonly.yml"


def load():
    spec = importlib.util.spec_from_file_location("taxonomy_visibility", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TaxonomyReadOnlyTests(unittest.TestCase):
    def test_reviewed_scope(self):
        mod = load()
        sample = {"protocol": "taxonomy-visibility-v1",
                  "reference_id": 10, "target_ids": [11, 16, 21, 22, 29]}
        self.assertTrue(mod.valid_request(sample))
        for override in (
            {"reference_id": 11},
            {"target_ids": []},
            {"target_ids": [10]},
            {"target_ids": [11, 11]},
            {"target_ids": [True]},
            {"target_ids": ["11"]},
            {"target_ids": list(range(11, 18))},
            {"protocol": "wrong"},
            {"extra": 99},
        ):
            with self.subTest(override=override):
                self.assertFalse(mod.valid_request(dict(sample, **override)))

    def test_post_ai_snapshot_diff(self):
        mod = load()
        after = {"id": 10, "document_type_id": 5, "tag_ids": [3, 4]}
        self.assertEqual(mod.manual_changes(after, 9, [3, 4, 8], 10),
                         (True, [8], []))
        self.assertEqual(mod.manual_changes(after, 5, [3, 4], 10),
                         (False, [], []))
        with self.assertRaises(ValueError):
            mod.manual_changes({"id": 11, "tag_ids": []}, None, [], 10)

    def test_input_failure_does_not_touch_paperless(self):
        process = subprocess.run(
            [sys.executable, "-c", SRC.read_text() + "\nmain()"],
            input=json.dumps({"protocol": "taxonomy-visibility-v1",
                              "reference_id": 10, "target_ids": [11, 11]}),
            capture_output=True, text=True, check=True, timeout=5,
        )
        self.assertIn('"STATUS": "INPUT_REJECTED"', process.stdout)
        self.assertIn('"CHANGED": false', process.stdout)

    def test_read_only_guards(self):
        source = SRC.read_text()
        play = PLAY.read_text()
        for snippet in ("mode=ro", "PRAGMA query_only=ON",
                        "permitted_object_ids", "MAX_TARGETS = 6"):
            self.assertIn(snippet, source)
        assert "get_ai_document_classification(" not in source
        config = yaml.safe_load(play)[0]
        self.assertEqual(config["hosts"], "venombox")
        self.assertTrue(config["become"])
        self.assertFalse(config["gather_facts"])
        commands = [t for t in config["tasks"] if "ansible.builtin.command" in t]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(t["no_log"] and t["changed_when"] is False
                            for t in commands))


if __name__ == "__main__":
    unittest.main()
