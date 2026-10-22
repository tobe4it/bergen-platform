"""Pure synthetic lifecycle regression for family metadata grants.

Does not connect to a live database, create documents, alter ACLs or require
Django. Extracts the exact two production policy functions using AST.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/files/paperless/reconcile_metadata_with_provenance.py"

FAMILY_ID = 7
THOMAS_ID = 3
NADJA_ID = 4
LINDA_ID = 5
VIEW_TAG = 80
VIEW_TYPE = 90
VIEW_CORRESPONDENT = 91


class SyntheticPaperlessMetadataLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ast.parse(SOURCE.read_text())
        name_set = {"delta", "user_metadata_policy"}
        functions = [node for node in source.body
                     if isinstance(node, ast.FunctionDef)
                     and node.name in name_set]
        assert len(functions) == len(name_set)
        namespace = {}
        exec(compile(ast.Module(body=functions, type_ignores=[]),
                     "<synthetic-taxonomy-policy>", "exec"), namespace)
        cls.delta = staticmethod(namespace["delta"])
        cls.policy = staticmethod(namespace["user_metadata_policy"])

    def test_one_new_tag_is_shared_but_old_manual_grants_are_not_adopted(self):
        existing = ("group", FAMILY_ID, VIEW_TAG, "38")
        brand_new = ("group", FAMILY_ID, VIEW_TAG, "39")
        add, remove = self.delta({existing, brand_new}, {existing}, set())
        self.assertEqual(add, {brand_new})
        self.assertEqual(remove, set())

        # After the first automated apply: 39 is managed, 38 stays manual.
        add, remove = self.delta({existing, brand_new},
                                 {existing, brand_new}, {brand_new})
        self.assertEqual((add, remove), (set(), set()))

        # Once new tag 39 is deleted, only its provenance-owned grant
        # is eligible for cleanup, not manual tag 38.
        add, remove = self.delta({existing},
                                 {existing, brand_new}, {brand_new})
        self.assertEqual(add, set())
        self.assertEqual(remove, {brand_new})

    def test_document_metadata_scoping_respects_actual_viewable_docs(self):
        # Synthetic doc 1: Eltern, doc 2: Thomas only, doc 3: shared.
        docs = {
            1: (1, THOMAS_ID, 10, 20),
            2: (2, THOMAS_ID, 11, 21),
            3: (3, NADJA_ID, 12, 22),
        }
        thomas, types, corrs = self.policy(
            THOMAS_ID, {1, 2, 3}, docs, VIEW_TYPE,
            VIEW_CORRESPONDENT, set(), set(), set())
        nadja, ntypes, ncorrs = self.policy(
            NADJA_ID, {3}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            set(), set(), set())
        linda, ltypes, lcorrs = self.policy(
            LINDA_ID, {3}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            set(), set(), set())

        self.assertEqual(types, {10, 11, 12})
        self.assertEqual(corrs, {20, 21, 22})
        self.assertEqual(ntypes, {12})
        self.assertEqual(ncorrs, {22})
        self.assertEqual(ltypes, {12})
        self.assertEqual(lcorrs, {22})

        self.assertIn(("user", THOMAS_ID, VIEW_TYPE, "11"), thomas)
        for other in (nadja, linda):
            self.assertTrue(all(grant[3] not in {"10", "11", "20", "21"}
                                for grant in other))
            self.assertEqual(len(other), 2)

    def test_last_visible_correspondent_reassignment_removes_only_managed(self):
        docs = {
            1: (1, THOMAS_ID, 10, 20),
            2: (2, THOMAS_ID, 10, 20),
        }
        existing_manual = ("user", THOMAS_ID, VIEW_TYPE, "10")
        previously_managed = ("user", THOMAS_ID, VIEW_CORRESPONDENT, "20")
        managed = {previously_managed}
        current = {existing_manual, previously_managed}

        grants, _, _ = self.policy(
            THOMAS_ID, {1, 2}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            {10}, {20}, managed)
        self.assertEqual(grants, {previously_managed})
        self.assertEqual(self.delta(grants, current, managed), (set(), set()))

        # First of two documents loses correspondent: grant stays.
        docs[1] = (1, THOMAS_ID, 10, None)
        grants, _, _ = self.policy(
            THOMAS_ID, {1, 2}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            {10}, {20}, managed)
        self.assertEqual(self.delta(grants, current, managed), (set(), set()))

        # After the final visible document loses it, only the automated
        # direct view_correspondent row is eligible for removal.
        docs[2] = (2, THOMAS_ID, 10, None)
        grants, _, _ = self.policy(
            THOMAS_ID, {1, 2}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            {10}, {20}, managed)
        add, revoke = self.delta(grants, current, managed)
        self.assertEqual(add, set())
        self.assertEqual(revoke, {previously_managed})
        self.assertNotIn(existing_manual, revoke)

    def test_losing_document_view_revokes_provenance_only(self):
        docs = {1: (1, THOMAS_ID, 10, 20)}
        managed = {("user", NADJA_ID, VIEW_CORRESPONDENT, "20")}
        historic = ("user", NADJA_ID, VIEW_TYPE, "10")
        grants, _, _ = self.policy(
            NADJA_ID, set(), docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            {10}, {20}, managed)
        add, revoke = self.delta(grants, managed | {historic}, managed)
        self.assertEqual(add, set())
        self.assertEqual(revoke, managed)

    def test_manually_existing_unrelated_correspondent_is_never_adopted(self):
        docs = {1: (1, THOMAS_ID, 10, 20)}
        manual = ("user", NADJA_ID, VIEW_CORRESPONDENT, "99")
        wanted, _, _ = self.policy(
            NADJA_ID, {1}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            set(), {99}, set())
        add, revoke = self.delta(wanted, {manual}, set())
        self.assertIn(("user", NADJA_ID, VIEW_CORRESPONDENT, "20"), add)
        self.assertNotIn(manual, add)
        self.assertNotIn(manual, revoke)

    def test_renewed_run_after_grant_is_idempotent(self):
        docs = {1: (1, NADJA_ID, 10, 20)}
        required, _, _ = self.policy(
            NADJA_ID, {1}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            set(), set(), set())
        add, revoke = self.delta(required, set(), set())
        self.assertEqual(len(add), 2)
        self.assertEqual(revoke, set())
        after, _, _ = self.policy(
            NADJA_ID, {1}, docs, VIEW_TYPE, VIEW_CORRESPONDENT,
            {10}, {20}, add)
        self.assertEqual(self.delta(after, add, add), (set(), set()))

    def test_manual_grant_never_deleted_when_not_required(self):
        manual = ("user", THOMAS_ID, VIEW_TYPE, "77")
        add, revoke = self.delta(set(), {manual}, set())
        self.assertEqual((add, revoke), (set(), set()))


if __name__ == "__main__":
    unittest.main()
