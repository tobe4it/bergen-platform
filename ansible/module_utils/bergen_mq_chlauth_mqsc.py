"""Strict offline parser for *one command per invocation* IBM MQ MQSC evidence.

No subprocess, SSH or MQ invocation exists in this module. A later adapter
must run exactly one reviewed MQSC command and supply (returncode, stdout).
The parser deliberately refuses ambiguous, truncated and unsuccessful output.
"""
import re

from .bergen_mq_chlauth import ChlauthPlanError

_MQSC_END = (
    "One MQSC command read.",
    "No commands have a syntax error.",
    "All valid MQSC commands were processed.",
)
_KV = re.compile(r"([A-Z][A-Z0-9]*)\(([^()]*)\)")
_ERROR = re.compile(r"\bAMQ\d{4}E\b", re.IGNORECASE)


def require_success(rc, output):
    """Require one MQSC command and complete, clean processing."""
    if type(rc) is not int or rc != 0 or not isinstance(output, str):
        raise ChlauthPlanError("MQSC rc is nonzero or not verifiable")
    if any(output.count(marker) != 1 for marker in _MQSC_END):
        raise ChlauthPlanError("MQSC output lacks exactly one clean completion")
    if _ERROR.search(output) or re.search(
            r"(could not be processed|syntax error detected)", output, re.I):
        raise ChlauthPlanError("MQSC reported a command-processing error")
    return output


def channel_auth_records(rc, output):
    """Return all unambiguous CHLAUTH records from DISPLAY CHLAUTH(*) ALL."""
    require_success(rc, output)
    # A record has exactly one AMQ8878I heading and one CHLAUTH + TYPE pair.
    heads = list(re.finditer(r"(?m)^AMQ8878I: Display channel authentication record details\.", output))
    if not heads:
        raise ChlauthPlanError("No CHLAUTH record evidence")
    records = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else output.find(
            "One MQSC command read.", head.end())
        if end < 0:
            raise ChlauthPlanError("CHLAUTH record boundaries are ambiguous")
        chunk = output[head.end():end]
        pairs = _KV.findall(chunk)
        if not pairs:
            raise ChlauthPlanError("Empty channel authentication record")
        record = {}
        for key, value in pairs:
            if key in record:
                raise ChlauthPlanError("Repeated CHLAUTH attribute " + key)
            record[key] = value.strip()
        if not record.get("CHLAUTH") or not record.get("TYPE"):
            raise ChlauthPlanError("Channel authentication identity missing")
        records.append(record)
    return records


def exact_records(records, receiver):
    """Select only rules whose literal channel profile matches receiver."""
    if not isinstance(records, list):
        raise ChlauthPlanError("Invalid CHLAUTH snapshot")
    return [row for row in records if row.get("CHLAUTH") == receiver]


def require_exact_fixture_records(records, spec, stage):
    """Conservative readback for deny/allow/no_allow/clean fixture stages.

    An exact channel name is necessary but not sufficient for run ownership.
    The caller must have independently checked no initial record and retained
    exclusive control during the fixture.
    """
    found = exact_records(records, spec["receiver"])
    if stage in ("clean",):
        if found:
            raise ChlauthPlanError("Residual CHLAUTH records remain")
        return True
    if stage not in ("deny", "receiver", "allow", "no_allow", "no_receiver"):
        raise ChlauthPlanError("Unsupported CHLAUTH verification phase")
    if len(found) not in (1, 2):
        raise ChlauthPlanError("Unexpected number of exact fixture rules")

    deny = [r for r in found if r.get("TYPE") == "ADDRESSMAP"]
    allowed = [r for r in found if r.get("TYPE") == "SSLPEERMAP"]
    if len(deny) != 1 or deny[0].get("ADDRESS") != "*" or (
            deny[0].get("USERSRC") != "NOACCESS"
            or deny[0].get("WARN") != "NO"):
        raise ChlauthPlanError("Default-deny rule not proven intact")
    if len(deny) + len(allowed) != len(found):
        raise ChlauthPlanError("Unexpected extra rule on fixture receiver")
    if stage in ("deny", "receiver", "no_allow", "no_receiver"):
        if allowed:
            raise ChlauthPlanError("Unexpected certificate allow rule present")
    elif stage == "allow":
        if len(allowed) != 1:
            raise ChlauthPlanError("Expected exactly one certificate mapping")
        rule = allowed[0]
        if any(rule.get(key) != value for key, value in (
                ("SSLPEER", spec["peer_subject"]),
                ("SSLCERTI", spec["peer_issuer"]),
                ("ADDRESS", spec["peer_ip"]),
                ("USERSRC", "MAP"),
                ("MCAUSER", spec["mcauser"]),
                ("WARN", "NO"))):
            raise ChlauthPlanError("Unexpected certificate mapping attributes")
    return True


def require_receiver_definition(rc, output, spec):
    """Accept exactly one receiver with expected TLS and non-admin MCAUSER."""
    require_success(rc, output)
    heads = re.findall(r"(?m)^AMQ8414I: Display Channel details\.", output)
    if len(heads) != 1:
        raise ChlauthPlanError("No unique receiver definition evidence")
    pairs = _KV.findall(output)
    attrs = {}
    for key, value in pairs:
        if key in attrs:
            raise ChlauthPlanError("Duplicate channel attribute: " + key)
        attrs[key] = value.strip()
    if any(attrs.get(key) != value for key, value in (
            ("CHANNEL", spec["receiver"]),
            ("CHLTYPE", "RCVR"),
            ("SSLCIPH", "TLS_AES_256_GCM_SHA384"),
            ("SSLCAUTH", "REQUIRED"),
            ("CERTLABL", "bergentransport"),
            ("MCAUSER", spec["mcauser"]))):
        raise ChlauthPlanError("Unexpected receiver TLS/MCAUSER attributes")
    return True
