"""Offline-only CHLAUTH recovery triage against operator-supplied MQ snapshots.

This module DOES NOT query MQ, decide object ownership or authorize cleanup.
A matching name, attributes and journal are never sufficient to prove that an
object still belongs to the original test run. No write or auto-repair path.
"""
from .bergen_mq_chlauth import ChlauthPlanError, LAB, make_plan
from .bergen_mq_chlauth_journal import recovery_report


def _expected_spec(prefix):
    return make_plan(
        prefix,
        {
            side: {"qmgr": node["qmgr"], "host": node["host"], "port": 1414}
            for side, node in LAB.items()
        },
    )


def _channel_matches(attrs, spec):
    expected = {
        "CHANNEL": spec["receiver"],
        "CHLTYPE": "RCVR",
        "SSLCIPH": "TLS_AES_256_GCM_SHA384",
        "SSLCAUTH": "REQUIRED",
        "CERTLABL": "bergentransport",
        "MCAUSER": spec["mcauser"],
    }
    return isinstance(attrs, dict) and all(
        attrs.get(key) == value for key, value in expected.items()
    )


def _rule_is_expected(record, spec):
    if not isinstance(record, dict) or record.get("CHLAUTH") != spec["receiver"]:
        return False
    if record.get("TYPE") == "ADDRESSMAP":
        fields = {"ADDRESS": "*", "USERSRC": "NOACCESS", "WARN": "NO"}
    elif record.get("TYPE") == "SSLPEERMAP":
        fields = {
            "SSLPEER": spec["peer_subject"],
            "SSLCERTI": spec["peer_issuer"],
            "ADDRESS": spec["peer_ip"],
            "USERSRC": "MAP",
            "MCAUSER": spec["mcauser"],
            "WARN": "NO",
        }
    else:
        return False
    return all(record.get(key) == value for key, value in fields.items())


def _side_result(side, spec, observed):
    """Treat supplied parsed observations as untrusted; never grant ownership."""
    if not isinstance(observed, dict) or set(observed) != {
            "qmgr", "channel", "rules"}:
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "Missing or extra evidence"}
    if observed["qmgr"] != spec["qmgr"]:
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "QMgr identity mismatch"}
    channel, rules = observed["channel"], observed["rules"]
    if not isinstance(channel, dict) or set(channel) != {"status", "attributes"}:
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "Channel observation malformed"}
    if not isinstance(rules, list) or not all(isinstance(row, dict) for row in rules):
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "CHLAUTH observation malformed"}
    status = channel["status"]
    if status == "ABSENT" and channel["attributes"] is not None:
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "Contradictory channel observation"}
    if status == "PRESENT" and not isinstance(channel["attributes"], dict):
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "Channel attributes missing"}
    if status not in ("ABSENT", "PRESENT"):
        return {"classification": "INCOMPLETE_EVIDENCE", "reason": "Channel absence/presence unproven"}
    # Only exact-profile rules are relevant. Any unexpected exact-profile
    # rule must be treated as possible third-party configuration.
    exact = [r for r in rules if r.get("CHLAUTH") == spec["receiver"]]
    if any(not _rule_is_expected(rule, spec) for rule in exact):
        return {"classification": "FOREIGN_OR_MODIFIED_OBJECT_POSSIBLE",
                "reason": "Unexpected exact-profile CHLAUTH rule"}
    kinds = [r["TYPE"] for r in exact]
    if len(kinds) != len(set(kinds)):
        return {"classification": "FOREIGN_OR_MODIFIED_OBJECT_POSSIBLE",
                "reason": "Duplicate exact-profile CHLAUTH rule type"}
    if status == "PRESENT" and not _channel_matches(channel["attributes"], spec):
        return {"classification": "FOREIGN_OR_MODIFIED_OBJECT_POSSIBLE",
                "reason": "Receiver attributes differ from fixture plan"}
    if status == "ABSENT" and not exact:
        return {"classification": "NO_FIXTURE_OBJECTS_REPORTED",
                "reason": "Supplied observations report no exact fixture objects"}
    return {"classification": "MATCHING_ATTRIBUTES_OWNERSHIP_UNPROVEN",
            "reason": "Same name and attributes never prove run ownership"}


def triage_recovery(journal_path, snapshots):
    """Correlate valid journal with untrusted observations; never delete.

    snapshots[side] needs:
      qmgr: exact queue manager name
      channel: {status: ABSENT|PRESENT, attributes: None|parsed DISPLAY CHANNEL}
      rules: full parsed DISPLAY CHLAUTH(*) record list
    Snapshots must come from independently validated, current MQ readbacks
    for operational usefulness. This function cannot prove their provenance.
    """
    report = recovery_report(journal_path)
    plan = _expected_spec(report["fixture"])
    if not isinstance(snapshots, dict) or set(snapshots) != {"a", "b"}:
        raise ChlauthPlanError("Two separate MQ snapshot sets required")
    result = {
        side: _side_result(side, plan[side], snapshots[side])
        for side in ("a", "b")
    }
    classifications = {item["classification"] for item in result.values()}
    if ("FOREIGN_OR_MODIFIED_OBJECT_POSSIBLE" in classifications
            or (report["state"] == "CLEAN_RECORDED"
                and "MATCHING_ATTRIBUTES_OWNERSHIP_UNPROVEN" in classifications)):
        assessment = "COLLISION_OR_POST_CLEAN_DRIFT_POSSIBLE"
    elif "INCOMPLETE_EVIDENCE" in classifications:
        assessment = "EVIDENCE_INCOMPLETE"
    elif classifications == {"NO_FIXTURE_OBJECTS_REPORTED"}:
        assessment = "NO_EXACT_FIXTURE_OBJECTS_REPORTED"
    else:
        assessment = "RESIDUAL_OBJECT_OWNERSHIP_UNPROVEN"
    return {
        "fixture": report["fixture"],
        "journal_state": report["state"],
        "assessment": assessment,
        "sides": result,
        "snapshots_are_untrusted_inputs": True,
        "can_auto_cleanup": False,
        "can_delete_matching_objects": False,
        "can_authorize_live_apply": False,
        "requires_independent_mq_readback_and_manual_review": True,
    }
