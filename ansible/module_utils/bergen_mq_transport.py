"""Per-run, fail-closed IBM MQ SDR/RCVR transport fixtures.

This module never changes channel authority, key repositories, certificates,
queue-manager settings or firewall rules. Unknown channel/queue state is unsafe.
"""
import re
import time
from ansible.module_utils.bergen_mq import MQError, discover, reconcile, responses
from ansible.module_utils.bergen_mq_audit_names import (
    validate_run, channel_name, transmission_queue,
)

CIPHER = "TLS_AES_256_GCM_SHA384"
TRANSPORT_CERTLABL = "bergentransport"
SIDES = (("a", "b"), ("b", "a"))
CHANNEL_NAME = re.compile(r"^AUDIT\.[A-F0-9]{7}\.[AB]2[AB]$")
ACTIVE_TIMEOUT = 25
STOP_TIMEOUT = 25


def declarations(prefix, nodes):
    if not re.fullmatch(r"AUDIT\.[A-F0-9]{7}", prefix):
        raise MQError("Invalid unique audit prefix")
    result = {}
    for side, destination in SIDES:
        channel = channel_name(prefix, side, destination)
        xmitq = transmission_queue(prefix, side)
        peer = nodes[destination]
        if not CHANNEL_NAME.fullmatch(channel):
            raise MQError("Channel name outside run-scoped namespace")
        if not re.fullmatch(r"[0-9A-Za-z.-]+", str(peer["host"])):
            raise MQError("Destination host unsuitable for MQ CONNAME")
        port = int(peer.get("port", 1414))
        if not 1 <= port <= 65535:
            raise MQError("Invalid destination port")
        result[side] = dict(destination=destination, sender=channel, receiver=channel,
                            xmitq=xmitq, objects=[
            dict(name=xmitq, type="qlocal", state="present",
                 attributes=dict(usage="xmitq", defpsist="yes",
                                 descr="Bergen audit temporary transmission queue")),
            dict(name=channel, type="channel", state="present",
                 attributes=dict(chltype="sdr", conname="%s(%s)" % (peer["host"], port),
                                 xmitq=xmitq, sslciph=CIPHER, certlabl=TRANSPORT_CERTLABL, hbint=5,
                                 descr="Bergen audit temporary TLS sender")),
        ])
    # Each receiver is defined on the opposite queue manager.
    for side, destination in SIDES:
        channel = result[side]["sender"]
        result[destination]["objects"].append(
            dict(name=channel, type="channel", state="present",
                 attributes=dict(chltype="rcvr", sslciph=CIPHER, certlabl=TRANSPORT_CERTLABL, hbint=5,
                                 sslcauth="required",
                                 descr="Bergen audit temporary TLS receiver")))
    return result


def channel_status(client, name):
    """Read *current* channel state; never infer TLS from configured SSLCIPH."""
    rows = responses(client.command("display", "chstatus", name,
                                    response_parameters=["all"]), allow_missing=True)
    if not rows:
        return None
    matches = [r.get("parameters") for r in rows if isinstance(r.get("parameters"), dict)]
    if len(matches) != 1:
        raise MQError("Ambiguous or incomplete channel status")
    current = {k.lower(): str(v).lower() for k, v in matches[0].items()}
    if current.get("channel", "").upper() != name:
        raise MQError("Channel status identity mismatch")
    return current


def depth(client, name):
    current = discover(client, dict(name=name, type="qlocal", state="present", attributes={}))
    if not current or current.get("usage", "").lower() != "xmitq":
        raise MQError("Expected run-owned XMITQ absent or wrong usage")
    value = current.get("curdepth")
    if value is None or str(value).strip() not in ("0",):
        raise MQError("Transmission queue not proven empty")
    rows = responses(client.command("display", "qstatus", name,
                                    response_parameters=["uncom"]))
    if len(rows) != 1 or not isinstance(rows[0].get("parameters"), dict):
        raise MQError("Unable to determine pending XMITQ units of work")
    status = {k.lower(): v for k, v in rows[0]["parameters"].items()}
    if str(status.get("uncom", "")).lower() not in ("0", "no"):
        raise MQError("Transmission queue has uncommitted changes or unknown UNCOM")
    return 0


def wait_running(client, name, *, timeout=ACTIVE_TIMEOUT, sleeper=time.sleep, clock=time.monotonic):
    deadline = clock() + timeout
    while True:
        status = channel_status(client, name)
        if status and status.get("status") == "running":
            if status.get("secprot") != "tlsv13" or status.get("sslciph", "").upper() != CIPHER:
                raise MQError("Channel running without required negotiated TLS 1.3 cipher")
            return dict(status="RUNNING", protocol="TLSV13", cipher=CIPHER)
        if clock() >= deadline:
            raise MQError("TLS channel RUNNING status not verified before timeout")
        sleeper(1)


def wait_inactive(client, name, *, timeout=STOP_TIMEOUT, sleeper=time.sleep, clock=time.monotonic):
    deadline = clock() + timeout
    while True:
        status = channel_status(client, name)
        # DISPLAY CHSTATUS CURRENT returns no row for inactive channels.
        if status is None:
            return
        if clock() >= deadline:
            raise MQError("Channel still has current status after quiesce timeout")
        sleeper(1)


class TransientTransport:
    """Handles only collision-free, uniquely named objects owned by this run."""

    def __init__(self, clients, nodes, prefix, *, sleeper=time.sleep, clock=time.monotonic):
        self.clients, self.nodes, self.prefix = clients, nodes, prefix
        self.specs = declarations(prefix, nodes)
        self.created = []  # (side, exact object declaration); includes uncertain writes
        self.started = []  # (side, exact name); includes uncertain START outcome
        self.sleeper, self.clock = sleeper, clock

    def preflight(self):
        # Check every name on both QMgr before the first DEFINE.
        for side in ("a", "b"):
            for obj in self.specs[side]["objects"]:
                if discover(self.clients[side], obj) is not None:
                    raise MQError("Audit namespace collision; no object changed")

    def create(self):
        self.preflight()
        for side in ("a", "b"):
            for obj in self.specs[side]["objects"]:
                # Register an attempted creation before REST, so a timeout is
                # never mistaken for an unowned/absent fixture.
                self.created.append((side, obj))
                reconcile(self.clients[side], [obj])
        return {side: {key: self.specs[side][key] for key in ("sender", "xmitq")}
                for side in ("a", "b")}

    def start(self):
        result = {}
        for side, destination in SIDES:
            channel = self.specs[side]["sender"]
            self.started.append((side, channel))
            responses(self.clients[side].command("start", "channel", channel))
            result[side] = wait_running(self.clients[side], channel,
                                        sleeper=self.sleeper, clock=self.clock)
            # Receiver must also negotiate TLS 1.3, never infer from sender only.
            result[destination + ":receiver"] = wait_running(
                self.clients[destination], channel,
                sleeper=self.sleeper, clock=self.clock)
        return result

    def cleanup(self, *, uncertain=False):
        """Return exact cleanup evidence and residual objects, never FORCE/PURGE.

        Any unknown START outcome or ambiguous STOP/state prevents destructive
        cleanup of affected channels and XMITQ. If remote probe timed out,
        retain everything because its outcome cannot be determined.
        """
        cleanup, residuals = [], []
        if uncertain:
            for side, obj in self.created:
                residuals.append(dict(side=side, name=obj["name"], type=obj["type"],
                                      reason="Remote probe outcome uncertain"))
            return cleanup, residuals

        safe_sides = {"a": True, "b": True}
        for side, channel in reversed(self.started):
            try:
                state = channel_status(self.clients[side], channel)
                if state is None or state.get("indoubt") != "no":
                    raise MQError("Sender channel in-doubt state not proven clear")
                responses(self.clients[side].command("stop", "channel", channel,
                                                    parameters={"mode": "quiesce"}))
                wait_inactive(self.clients[side], channel,
                              sleeper=self.sleeper, clock=self.clock)
                destination = self.specs[side]["destination"]
                wait_inactive(self.clients[destination], channel,
                              sleeper=self.sleeper, clock=self.clock)
                depth(self.clients[side], self.specs[side]["xmitq"])
                cleanup.append(dict(side=side, name=channel, action="stop", status="PASS"))
            except Exception:
                safe_sides[side] = False
                safe_sides[self.specs[side]["destination"]] = False
                cleanup.append(dict(side=side, name=channel, action="stop",
                                    status="FAIL", detail="Stop, TLS state or XMITQ depth unverified"))

        # The reverse direction shares a receiver on the opposite QMgr;
        # a failure on either side makes all channel deletions unsafe.
        if not all(safe_sides.values()):
            for side, obj in self.created:
                residuals.append(dict(side=side, name=obj["name"], type=obj["type"],
                                      reason="Transport shutdown was not verified"))
            return cleanup, residuals

        # Sender START may fail before command application; absence is safe
        # only once all channel status and XMITQ checks have succeeded.
        for side, obj in reversed(self.created):
            try:
                if obj["type"] == "qlocal":
                    depth(self.clients[side], obj["name"])
                elif channel_status(self.clients[side], obj["name"]) is not None:
                    raise MQError("Channel still active")
                gone = dict(name=obj["name"], type=obj["type"], state="absent")
                reconcile(self.clients[side], [gone], allow_deletion=True)
                if discover(self.clients[side], gone) is not None:
                    raise MQError("Deleted transport object still exists")
                cleanup.append(dict(side=side, name=obj["name"], action="delete",
                                    status="PASS"))
            except Exception:
                residuals.append(dict(side=side, name=obj["name"], type=obj["type"],
                                      reason="Deletion or absence could not be proven"))
                cleanup.append(dict(side=side, name=obj["name"], action="delete",
                                    status="FAIL"))
        return cleanup, residuals
