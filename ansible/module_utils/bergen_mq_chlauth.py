"""Pure, fail-closed CHLAUTH fixture planning for the two-QMgr evaluation lab.

This module NEVER runs MQSC. Every generated CHLAUTH record uses the exact
per-run receiver name; no wildcard rules or changes to BGT.CLIENT, * or
SYSTEM.* are permitted. The receiver must exist before MATCH(RUNCHECK).
"""

import ipaddress
import re

PREFIX = re.compile(r"^BGT\.[A-F0-9]{7}$")
CIPHER = "TLS_AES_256_GCM_SHA384"
CERTLABL = "bergentransport"

# Verified lab configuration; a topology change requires a code review rather
# than silently granting an unexpected IP / queue manager an identity.
LAB = {
    "a": {"qmgr": "BERGENLAB", "host": "192.168.20.212",
          "transport_user": "bgttransa", "group": "MQBGTTRANSA"},
    "b": {"qmgr": "BERGENLABB", "host": "192.168.20.156",
          "transport_user": "bgttransb", "group": "MQBGTTRANSB"},
}
SUBJECT = {"a": "CN=bergen-mq-lab transport",
           "b": "CN=bergen-mq-lab-b transport"}
ISSUER = {"a": "CN=Bergen MQ Transport CA BERGENLAB",
          "b": "CN=Bergen MQ Transport CA BERGENLABB"}


class ChlauthPlanError(ValueError):
    """Unsafe or incomplete fixture specification."""


def _quote(value):
    """Only values prevalidated by this module reach MQSC single quotes."""
    if not isinstance(value, str) or not value or "'" in value or "\n" in value or "\r" in value:
        raise ChlauthPlanError("Invalid MQSC value")
    return "'" + value + "'"


def _validated_nodes(nodes):
    if not isinstance(nodes, dict) or set(nodes) != {"a", "b"}:
        raise ChlauthPlanError("Exactly two configured queue managers required")
    for side in ("a", "b"):
        node, expected = nodes[side], LAB[side]
        if not isinstance(node, dict) or node.get("qmgr") != expected["qmgr"]:
            raise ChlauthPlanError("Unknown queue manager for transport CHLAUTH")
        try:
            address = str(ipaddress.IPv4Address(node["host"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ChlauthPlanError("Expected an explicit IPv4 peer") from exc
        if address != expected["host"]:
            raise ChlauthPlanError("Unreviewed MQ peer IP; refuse to issue CHLAUTH")
        if int(node.get("port", 1414)) != 1414:
            raise ChlauthPlanError("Unreviewed MQ listener port")
    return nodes


def make_plan(prefix, nodes):
    """Generate exact scoped MQSC commands; returns no executable side effects.

    For each *receiver*:
      a: B2A, certificate presented by B, mapped to bgttransa
      b: A2B, certificate presented by A, mapped to bgttransb

    Order matters: preflight, DEFINE RCVR, deny all, allow one certificate,
    RUNCHECK positive and negatives, then guarded cleanup. Cleanup commands
    are NOT permission to delete unowned or active objects.
    """
    if not isinstance(prefix, str) or not PREFIX.fullmatch(prefix):
        raise ChlauthPlanError("Prefix must be BGT.<exactly seven uppercase hexadecimal digits>")
    _validated_nodes(nodes)
    result = {}
    for destination, sender, suffix in (("a", "b", "B2A"), ("b", "a", "A2B")):
        channel = prefix + "." + suffix
        peer_ip = LAB[sender]["host"]
        peer_qmgr = LAB[sender]["qmgr"]
        peer_subject = SUBJECT[sender]
        peer_issuer = ISSUER[sender]
        user = LAB[destination]["transport_user"]
        c = _quote(channel)
        address = _quote(peer_ip)
        subject = _quote(peer_subject)
        issuer = _quote(peer_issuer)
        reject_subject = _quote("CN=Unrecognized Bergen MQ Transport")
        reject_issuer = _quote("CN=Untrusted MQ Transport CA")
        # A single alternate address cannot accidentally equal the expected
        # peer, and is syntactically valid for the simulated CHLAUTH check.
        reject_address = _quote(LAB[destination]["host"])
        base = "DISPLAY CHLAUTH(%s) TYPE(ALL) MATCH(RUNCHECK)" % c
        def runcheck(ip, dn, ca):
            return ("%s ADDRESS(%s) SSLPEER(%s) SSLCERTI(%s) QMNAME(%s)" %
                    (base, ip, dn, ca, _quote(peer_qmgr)))

        deny = ("SET CHLAUTH(%s) TYPE(ADDRESSMAP) ADDRESS('*') "
                "USERSRC(NOACCESS) WARN(NO) ACTION(ADD)") % c
        allow = ("SET CHLAUTH(%s) TYPE(SSLPEERMAP) SSLPEER(%s) "
                 "SSLCERTI(%s) ADDRESS(%s) USERSRC(MAP) MCAUSER(%s) "
                 "WARN(NO) ACTION(ADD)") % (
                     c, subject, issuer, address, _quote(user))
        # ACTION(REMOVE) uses only the identity keys; never REMOVEALL.
        remove_allow = ("SET CHLAUTH(%s) TYPE(SSLPEERMAP) SSLPEER(%s) "
                        "SSLCERTI(%s) ADDRESS(%s) ACTION(REMOVE)") % (
                            c, subject, issuer, address)
        remove_deny = ("SET CHLAUTH(%s) TYPE(ADDRESSMAP) ADDRESS('*') "
                       "ACTION(REMOVE)") % c

        result[destination] = {
            "qmgr": LAB[destination]["qmgr"],
            "receiver": channel,
            "peer_qmgr": peer_qmgr,
            "peer_ip": peer_ip,
            "peer_subject": peer_subject,
            "peer_issuer": peer_issuer,
            "mcauser": user,
            "group": LAB[destination]["group"],
            "preflight": [
                "DISPLAY QMGR CHLAUTH",
                "DISPLAY CHANNEL(%s) CHLTYPE SSLCAUTH SSLCIPH CERTLABL" % c,
                "DISPLAY CHLAUTH(%s) TYPE(ALL) MATCH(EXACT)" % c,
                "DISPLAY CHLAUTH('BGT.CLIENT') TYPE(ALL) MATCH(EXACT)",
            ],
            "define_receiver": (
                "DEFINE CHANNEL(%s) CHLTYPE(RCVR) "
                "SSLCIPH(%s) SSLCAUTH(REQUIRED) CERTLABL(%s) HBINT(5) "
                "DESCR('Bergen transient mTLS CHLAUTH fixture')" %
                (c, _quote(CIPHER), _quote(CERTLABL))),
            "add_rules": [deny, allow],
            "cases": [
                {"name": "valid_certificate", "expect": "MAP",
                 "mcauser": user, "command": runcheck(address, subject, issuer)},
                {"name": "wrong_subject", "expect": "NOACCESS",
                 "command": runcheck(address, reject_subject, issuer)},
                {"name": "wrong_issuer", "expect": "NOACCESS",
                 "command": runcheck(address, subject, reject_issuer)},
                {"name": "wrong_source_ip", "expect": "NOACCESS",
                 "command": runcheck(reject_address, subject, issuer)},
            ],
            # Never remove the deny rule while the receiver still exists:
            # authorization must fail closed if receiver deletion fails.
            "cleanup": [remove_allow, "DELETE CHANNEL(%s)" % c,
                        remove_deny],
        }
    return result


def verify_runcheck(output, receiver, expected, user=None):
    """Conservatively classify *observed* MQSC output (not a live TLS test).

    Reject missing-channel errors, syntax errors, ambiguous responses and
    unexpected rules. An actual TLS handshake remains independently required.
    """
    if not isinstance(output, str) or not isinstance(receiver, str):
        raise ChlauthPlanError("Invalid MQSC evidence")
    if not PREFIX.fullmatch(receiver.rsplit(".", 1)[0]) or receiver not in (
            receiver.rsplit(".", 1)[0] + ".B2A",
            receiver.rsplit(".", 1)[0] + ".A2B"):
        raise ChlauthPlanError("Not a run-owned receiver name")
    upper = output.upper()
    if ("NO COMMANDS HAVE A SYNTAX ERROR." not in upper
            or "ALL VALID MQSC COMMANDS WERE PROCESSED." not in upper
            or "AMQ9519E" in upper):
        raise ChlauthPlanError("MQSC failed, was incomplete or receiver channel is absent")
    if "AMQ8878I" not in upper or ("CHLAUTH(%s)" % receiver) not in upper:
        raise ChlauthPlanError("No exact channel authentication match evidence")
    if len(re.findall(r"\bTYPE\((SSLPEERMAP|ADDRESSMAP)\)", upper)) != 1:
        raise ChlauthPlanError("Ambiguous CHLAUTH response")
    if expected == "MAP":
        if user not in {"bgttransa", "bgttransb"}:
            raise ChlauthPlanError("Unknown MCAUSER")
        if ("TYPE(SSLPEERMAP)" not in upper
                or "USERSRC(MAP)" not in upper
                or ("MCAUSER(%s)" % user.upper()) not in upper):
            raise ChlauthPlanError("Expected certificate-bound mapping was not proven")
    elif expected == "NOACCESS":
        if "TYPE(ADDRESSMAP)" not in upper or "USERSRC(NOACCESS)" not in upper:
            raise ChlauthPlanError("Expected default-deny outcome was not proven")
    else:
        raise ChlauthPlanError("Unknown expected RUNCHECK result")
    return True
