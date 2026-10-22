#!/usr/bin/env python3
"""No-network, synthetic graph regression tests for read-only Rocky symlink diagnostic."""
import importlib.util
from pathlib import Path
import sys
import unittest

SRC = (Path(__file__).resolve().parents[1] / "ansible/files/nextcloud")
sys.path.insert(0, str(SRC))
spec = importlib.util.spec_from_file_location(
    "rocky_link_diagnostic", SRC / "diagnose_rocky_lxc_rootfs_symlinks.py"
)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class RockySymlinkDiagnosticTests(unittest.TestCase):
    def test_resolved_absolute_and_relative_with_bounded_categories(self):
        names = {"usr/lib/real", "etc/rocky-release"}
        implicit = {"usr", "usr/lib", "etc"}
        links = {
            "var/absolute": "/usr/lib/real",
            "var/relative": "../etc/rocky-release",
            "var/implicit": "/usr/lib",
            "var/dangling": "../usr/lib/missing",
            "var/runtime": "/proc/self/exe",
        }
        result = diag.diagnose_graph(names, links, implicit)
        self.assertEqual(result["classification"], {
            "absolute_archived_target": 1,
            "absolute_dangling": 1,
            "absolute_implicit_directory": 1,
            "relative_archived_target": 1,
            "relative_dangling": 1,
        })
        self.assertEqual(result["dangling_target_classes"], {
            "absolute_runtime_tree": 1,
            "relative_usr_tree": 1,
        })
        self.assertEqual(result["dangling_parent_classes"], {
            "parent_missing": 1, "parent_present": 1,
        })
        self.assertNotIn("missing", str(result).replace("parent_missing", ""))

    def test_loops_and_escape_are_categorized_without_approval(self):
        links = {
            "var/a": "b", "var/b": "a",
            "var/escape": "../../../etc/passwd",
            "var/nul": "foo\\x00bar",
        }
        # Replace the literal escape sequence with a real NUL in memory.
        links["var/nul"] = "foo" + chr(0) + "bar"
        result = diag.diagnose_graph(set(), links, set())
        self.assertEqual(result["classification"], {
            "relative_invalid_symlink_target": 1,
            "relative_symlink_escapes_root": 1,
            "relative_symlink_loop_or_depth": 2,
        })
        self.assertEqual(result["dangling_target_classes"], {})
        self.assertEqual(result["symlinks_checked"], 4)


if __name__ == "__main__":
    unittest.main()
