"""Pure naming contract for run-scoped IBM MQ AUDIT fixtures.

Existing BGT.CLIENT and transport LDAP/certificate identities are untouched.
The labels are naming conventions, not proof of MQ object ownership.
"""
import re

APPLICATION = "AUDIT"
RUN = re.compile(r"\AAUDIT\.[A-F0-9]{7}\Z")
CHANNEL = re.compile(r"\AAUDIT\.[A-F0-9]{7}\.[AB]2[AB]\Z")
CHANNEL_LIMIT = 20
QUEUE_LIMIT = 48


def valid_run(prefix):
    return isinstance(prefix, str) and RUN.fullmatch(prefix) is not None


def validate_run(prefix):
    if not valid_run(prefix):
        raise ValueError("Expected AUDIT.<7 uppercase hex characters>")
    return prefix


def channel_name(prefix, origin, destination):
    validate_run(prefix)
    if (origin, destination) not in (("a", "b"), ("b", "a")):
        raise ValueError("Audit channel direction must be a->b or b->a")
    name = prefix + "." + origin.upper() + "2" + destination.upper()
    if len(name) > CHANNEL_LIMIT or not CHANNEL.fullmatch(name):
        raise ValueError("Audit channel exceeds allowed channel identity")
    return name


def _queue(name, required_prefix):
    if (not isinstance(name, str) or not name.startswith(required_prefix)
            or len(name) > QUEUE_LIMIT
            or not re.fullmatch(r"[A-Z0-9.]+", name)
            or ".." in name):
        raise ValueError("Invalid audit queue name")
    return name


def local_queue(prefix, suffix):
    validate_run(prefix)
    if not isinstance(suffix, str) or not re.fullmatch(r"[A-Z0-9.]+", suffix):
        raise ValueError("Invalid audit queue suffix")
    return _queue("LQ." + prefix + "." + suffix, "LQ.AUDIT.")


def alias_queue(prefix, suffix):
    validate_run(prefix)
    if not isinstance(suffix, str) or not re.fullmatch(r"[A-Z0-9.]+", suffix):
        raise ValueError("Invalid audit queue suffix")
    return _queue(prefix + "." + suffix, "AUDIT.")


def remote_queue(prefix, suffix):
    validate_run(prefix)
    if not isinstance(suffix, str) or not re.fullmatch(r"[A-Z0-9.]+", suffix):
        raise ValueError("Invalid audit queue suffix")
    return _queue("RQ." + prefix + "." + suffix, "RQ.AUDIT.")


def transmission_queue(prefix, side):
    validate_run(prefix)
    if side not in ("a", "b"):
        raise ValueError("Invalid audit XMITQ side")
    return _queue("XQ." + prefix + "." + side.upper() + "X", "XQ.AUDIT.")
