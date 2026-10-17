"""Privacy-preserving Open WebUI family group inventory; no mutations or PII output.

Run by Ansible filter on the controller only, never as an authorization
decision. Expected real names stay in ignored site-local variables.
"""
import re
from ansible.errors import AnsibleFilterError

_ROLES = ("family", "adults", "children")
_SUPPORTED = {"0.10.2", "0.12.3"}


def family_group_inventory(groups, expected, version):
    """Classify three stable family groups; intentionally omit IDs and names."""
    if not isinstance(version, str):
        raise AnsibleFilterError("Unsupported or missing Open WebUI version")
    match = re.fullmatch(r"v?(0[.]10[.]2|0[.]12[.]3)(?:[-+][A-Za-z0-9._-]+)?", version)
    if not match or match.group(1) not in _SUPPORTED:
        raise AnsibleFilterError("Unreviewed Open WebUI version; refuse group inventory")
    current = match.group(1)

    if not isinstance(expected, dict) or set(expected) != set(_ROLES):
        raise AnsibleFilterError("Require exactly family/adults/children expected roles")
    if any(not isinstance(expected[k], str) or
           not expected[k].strip() or expected[k] != expected[k].strip() or
           len(expected[k]) > 120 for k in _ROLES):
        raise AnsibleFilterError("Expected group names must be nonempty, exact and bounded")
    if len(set(expected.values())) != len(_ROLES):
        raise AnsibleFilterError("Family, adults and children must be distinct groups")

    if not isinstance(groups, list) or len(groups) > 1000:
        raise AnsibleFilterError("Malformed or oversized groups response")
    seen_ids = set()
    for group in groups:
        if not isinstance(group, dict):
            raise AnsibleFilterError("Malformed group response")
        ident, name = group.get("id"), group.get("name")
        if not isinstance(ident, str) or not ident or len(ident) > 256:
            raise AnsibleFilterError("Malformed group identity")
        if ident in seen_ids or not isinstance(name, str):
            raise AnsibleFilterError("Malformed or duplicate group identity")
        seen_ids.add(ident)

    statuses = {}
    for role in _ROLES:
        matches = [group for group in groups if group["name"] == expected[role]]
        if not matches:
            statuses[role] = "MISSING"
        elif len(matches) != 1:
            statuses[role] = "DUPLICATE"
        elif current == "0.10.2":
            statuses[role] = "PRESENT_LEGACY_FLAT"
        else:
            group = matches[0]
            if "parent_group_id" not in group:
                statuses[role] = "HIERARCHY_UNVERIFIED"
            elif group["parent_group_id"] is not None:
                statuses[role] = "NESTED_REVIEW_REQUIRED"
            else:
                statuses[role] = "PRESENT_ROOT"

    all_present = all(statuses[role] in
                      ("PRESENT_ROOT", "PRESENT_LEGACY_FLAT") for role in _ROLES)
    return {
        "VERSION_REVIEWED": "V0_10_2" if current == "0.10.2" else "V0_12_3",
        "FAMILY_GROUP": statuses["family"],
        "ADULTS_GROUP": statuses["adults"],
        "CHILDREN_GROUP": statuses["children"],
        "STATUS": "INVENTORY_PRESENT_ONLY" if all_present else "MANUAL_REVIEW_REQUIRED",
        "MEMBERSHIP_SEPARATION_PROVEN": "NO",
        "RESOURCE_ACL_SEPARATION_PROVEN": "NO",
        "EXISTING_SESSIONS_REVOKED": "NO",
        "GROUPS_OR_PERMISSIONS_CHANGED": "NO",
    }


class FilterModule:
    def filters(self):
        return {"bergen_ai_family_group_inventory": family_group_inventory}
