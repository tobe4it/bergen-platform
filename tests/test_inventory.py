"""Exercise the actual managed-inventory Jinja expressions without SSH/RPC."""
import copy
from pathlib import Path
import unittest

import yaml
from jinja2 import Environment, StrictUndefined
from ansible.plugins.filter.core import FilterModule

ROOT = Path(__file__).resolve().parents[1]
LEGACY_GROUP = "{{ lxc_inventory_group }}"
LEGACY_HOST = "{{ lxc_hostname }}"


class InventoryContracts(unittest.TestCase):
    def setUp(self):
        self.tasks = yaml.safe_load((ROOT / "ansible/playbooks/update-inventory.yml").read_text())[0]["tasks"]
        self.env = Environment(undefined=StrictUndefined)
        filters = FilterModule().filters()
        self.env.filters.update({name: filters[name] for name in ['combine', 'dict2items', 'items2dict']})

    def expression(self, text, context):
        return self.env.compile_expression(text.strip()[2:-2].strip())(**context)

    def reconcile(self, current):
        context = dict(inventory_current_data=copy.deepcopy(current),
                       lxc_inventory_group="mq_lab_nodes", lxc_hostname="bergen-mq-lab",
                       discovered_inventory_ipv4="192.0.2.212")
        start = False
        for task in self.tasks:
            if task["name"] == "Verwalteten Hosteintrag aufbauen":
                start = True
            if not start:
                continue
            if task["name"] == "Verwalteten Hosteintrag persistent speichern":
                break
            if "legacy" in task["name"].lower() and "Identify" not in task["name"]:
                if LEGACY_GROUP not in context["inventory_current_data"]["all"]["children"]:
                    continue
            if "ansible.builtin.assert" in task:
                for condition in task["ansible.builtin.assert"]["that"]:
                    if not self.env.compile_expression(condition)(**context):
                        raise ValueError("Ambiguous legacy entry")
            for key, value in task.get("ansible.builtin.set_fact", {}).items():
                context[key] = self.expression(value, context)
        return context["inventory_merged_data"]

    def test_resolved_keys_and_repeat_idempotence(self):
        seed = {"all": {"children": {"evcc_nodes": {"hosts": {"evcc": {"ansible_host": "192.0.2.124"}}}}}}
        result = self.reconcile(seed)
        self.assertEqual(result["all"]["children"]["evcc_nodes"], seed["all"]["children"]["evcc_nodes"])
        self.assertEqual(result["all"]["children"]["mq_lab_nodes"]["hosts"]["bergen-mq-lab"]["ansible_host"], "192.0.2.212")
        self.assertNotIn("{{", yaml.safe_dump(result))
        self.assertEqual(self.reconcile(result), result)

    def test_legacy_repair_preserves_unrelated_and_custom_settings(self):
        seed = {"all": {"vars": {"site": "test"}, "children": {
            "mail": {"hosts": {"mail": {"custom": True}}},
            LEGACY_GROUP: {"hosts": {LEGACY_HOST: {"ansible_host": "192.0.2.212", "custom": "retain"}}}}}}
        result = self.reconcile(seed)
        self.assertNotIn(LEGACY_GROUP, result["all"]["children"])
        self.assertEqual(result["all"]["children"]["mail"], seed["all"]["children"]["mail"])
        self.assertEqual(result["all"]["vars"], seed["all"]["vars"])
        self.assertEqual(result["all"]["children"]["mq_lab_nodes"]["hosts"]["bergen-mq-lab"]["custom"], "retain")
        self.assertEqual(self.reconcile(result), result)

    def test_legacy_different_address_or_extra_host_is_refused(self):
        for hosts in [{LEGACY_HOST: {"ansible_host": "192.0.2.99"}},
                      {LEGACY_HOST: {"ansible_host": "192.0.2.212"}, "other": {}}]:
            seed = {"all": {"children": {LEGACY_GROUP: {"hosts": hosts}}}}
            original = copy.deepcopy(seed)
            with self.assertRaises(ValueError):
                self.reconcile(seed)
            self.assertEqual(seed, original)

    def test_persistent_update_keeps_a_backup(self):
        task = next(t for t in self.tasks if t["name"] == "Verwalteten Hosteintrag persistent speichern")
        self.assertTrue(task["ansible.builtin.copy"]["backup"])
