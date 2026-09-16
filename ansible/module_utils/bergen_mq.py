"""Bounded IBM MQ desired-state reconciliation using JSON MQSC over REST.

No MQ client libraries, shell access, REPLACE, FORCE or message operations.
"""
import base64
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener


class MQError(Exception):
    pass


NAME = re.compile(r"^[A-Za-z0-9._/%-]{1,48}$")
CHANNEL_TYPES = {"sdr", "rcvr", "svrconn", "clntconn", "clussdr", "clusrcvr"}
# Restrict this first implementation to attributes with round-trippable DISPLAY
# values. MQSC command switches, write-only secrets and runtime counters are not
# accepted as desired attributes.
COMMON = {"descr": "text"}
ATTRIBUTES = {
    "qlocal": dict(COMMON, maxdepth="int", maxmsgl="int", defpsist="enum",
                   put="enum", get="enum", usage="enum"),
    "qremote": dict(COMMON, rname="text", rqmname="text", xmitq="text",
                    defpsist="enum", put="enum"),
    "qalias": dict(COMMON, target="text", targtype="enum", defpsist="enum",
                   put="enum", get="enum"),
    "qmodel": dict(COMMON, maxdepth="int", maxmsgl="int", defpsist="enum",
                   deftype="enum", put="enum", get="enum"),
    "channel": dict(COMMON, chltype="enum", conname="text", xmitq="text",
                    maxmsgl="int", hbint="int", kaint="int",
                    discint="int", sslciph="text", sslcauth="enum"),
    "topic": dict(COMMON, topicstr="text", pub="enum", sub="enum",
                  pubscope="enum", subscope="enum", defpsist="enum"),
    "namelist": dict(COMMON, names="list", nltype="enum"),
}
ENUM_VALUES = {
    "defpsist": {"yes", "no", "asparent"},
    "put": {"enabled", "disabled"}, "get": {"enabled", "disabled"},
    "usage": {"normal", "xmitq"}, "targtype": {"queue", "topic"},
    "deftype": {"permdyn", "tempdyn"}, "chltype": CHANNEL_TYPES,
    "sslcauth": {"required", "optional"},
    "pub": {"enabled", "disabled", "asparent"}, "sub": {"enabled", "disabled", "asparent"},
    "pubscope": {"qmgr", "all", "asparent"}, "subscope": {"qmgr", "all", "asparent"},
    "nltype": {"none", "queue", "cluster", "authinfo"},
}


def normalize(value, kind):
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MQError("Integer attributes require non-negative YAML integers")
        return value
    if kind == "list":
        if not isinstance(value, list) or any(not isinstance(v, str) or not NAME.fullmatch(v) for v in value):
            raise MQError("names must be a list of exact MQ names")
        return value
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise MQError("String attributes require strings without control characters; quote yes/no")
    return value.lower() if kind == "enum" else value.rstrip()


def validate_objects(objects, allow_deletion=False):
    if not isinstance(objects, list) or not objects:
        raise MQError("objects must be a non-empty list")
    result, identities = [], set()
    for obj in objects:
        if not isinstance(obj, dict) or set(obj) - {"name", "type", "state", "attributes"}:
            raise MQError("Object fields must be name, type, state and attributes")
        name, typ, state = obj.get("name"), obj.get("type"), obj.get("state", "present")
        if typ not in ATTRIBUTES or not isinstance(name, str) or not NAME.fullmatch(name):
            raise MQError("Unsupported object type or non-exact MQ name")
        if name.upper().startswith(("SYSTEM.", "AMQ.")):
            raise MQError("IBM/system-owned objects are not managed by this module")
        # Queue names share one namespace; reject declarations that would race
        # or attempt to convert a queue's type by deletion/recreation.
        identity = ("queue" if typ.startswith("q") else typ, name)
        if identity in identities:
            raise MQError("Duplicate object identity in desired state")
        identities.add(identity)
        if state not in {"present", "absent"}:
            raise MQError("state must be present or absent")
        if state == "absent" and not allow_deletion:
            raise MQError("state=absent requires allow_deletion=true, including in check mode")
        attrs = obj.get("attributes", {})
        if not isinstance(attrs, dict) or set(attrs) - set(ATTRIBUTES[typ]):
            raise MQError("Unsupported attribute for %s; see docs/MQ.md" % typ)
        if state == "absent" and attrs:
            raise MQError("Absent objects must not declare attributes")
        attrs = {k: normalize(v, ATTRIBUTES[typ][k]) for k, v in attrs.items()}
        for key, value in attrs.items():
            if ATTRIBUTES[typ][key] == "enum" and value not in ENUM_VALUES[key]:
                raise MQError("Unsupported enum value for %s" % key)
        if typ.startswith("q") and attrs.get("defpsist") == "asparent":
            raise MQError("Queue defpsist must be quoted yes or no")
        if typ == "channel" and state == "present" and attrs.get("chltype") not in CHANNEL_TYPES:
            raise MQError("Present channels require a supported chltype")
        result.append(dict(name=name, type=typ, state=state, attributes=attrs))
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MQError("REST redirects are refused to protect administrator credentials")


class RestClient:
    def __init__(self, endpoint, qmgr, username, password, ca_path=None, timeout=30):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not re.fullmatch(r"/ibmmq/rest/v[23]/?", parsed.path)):
            raise MQError("endpoint must be https://HOST:PORT/ibmmq/rest/v2 or v3 without credentials/query")
        if not isinstance(qmgr, str) or not NAME.fullmatch(qmgr):
            raise MQError("qmgr must be an exact queue manager name")
        if not username or not password or timeout <= 0:
            raise MQError("REST username/password and a positive timeout are required")
        self.url = endpoint.rstrip("/") + "/admin/action/qmgr/" + quote(qmgr, safe="") + "/mqsc"
        self.timeout = timeout
        self.auth = "Basic " + base64.b64encode((username + ":" + password).encode()).decode()
        context = ssl.create_default_context(cafile=ca_path)
        # Direct HTTPS only; never forward credentials through environment proxies.
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())

    def command(self, command, typ, name, parameters=None, response_parameters=None):
        body = dict(type="runCommandJSON", command=command, qualifier=typ, name=name)
        if parameters:
            body["parameters"] = parameters
        if response_parameters:
            body["responseParameters"] = response_parameters
        req = Request(self.url, json.dumps(body).encode(), method="POST", headers={
            "Authorization": self.auth, "Content-Type": "application/json",
            "Accept": "application/json", "ibm-mq-rest-csrf-token": "bergen-platform",
        })
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            # Do not expose response bodies or authorization headers in logs.
            raise MQError("MQ REST HTTP %s; verify endpoint, TLS, identity and authorities" % exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise MQError("MQ REST connection failed; verify DNS, route, TLS CA and timeout") from None
        except (ValueError, UnicodeError):
            raise MQError("MQ REST returned invalid JSON") from None
        return data


def responses(data, allow_missing=False):
    if (not isinstance(data, dict) or data.get("error")
            or "overallCompletionCode" not in data or "overallReasonCode" not in data
            or not isinstance(data.get("commandResponse"), list) or not data["commandResponse"]):
        raise MQError("MQ REST returned an error or an unsupported response structure")
    rows = data["commandResponse"]
    # A failing overall command must never be hidden by successful detail rows.
    overall = (data["overallCompletionCode"], data["overallReasonCode"])
    failures = []
    for row in rows:
        if not isinstance(row, dict) or "completionCode" not in row or "reasonCode" not in row:
            raise MQError("MQ REST command response lacks completion/reason codes")
        if row["completionCode"] != 0 or row["reasonCode"] != 0:
            failures.append((row["completionCode"], row["reasonCode"]))
    # Only MQRC_UNKNOWN_OBJECT_NAME is absence. HTTP 404, authorization failures,
    # syntax failures, warnings and unfamiliar MQ reason codes fail closed.
    if allow_missing and failures and all(code == (2, 2085) for code in failures) and all("parameters" not in row for row in rows) and overall in {(0, 0), (2, 2085), (2, 3008)}:
        return []
    if failures or overall != (0, 0):
        raise MQError("MQ command failed: overall=%s, detail=%s" % (overall, failures))
    return rows


def discover(client, obj):
    # For queues use DISPLAY QUEUE instead of DISPLAY QLOCAL so a conflicting
    # queue type is detected and never interpreted as a missing object.
    typ = "queue" if obj["type"].startswith("q") else obj["type"]
    rows = responses(client.command("display", typ, obj["name"], response_parameters=["all"]), allow_missing=True)
    attrs = [row["parameters"] for row in rows if isinstance(row.get("parameters"), dict)]
    if not rows:
        return None
    if len(attrs) != 1:
        raise MQError("DISPLAY must return exactly one structured object")
    current = {k.lower(): v for k, v in attrs[0].items()}
    identity_key = {"queue": "queue", "channel": "channel", "topic": "topic", "namelist": "namelist"}[typ]
    if current.get(identity_key) != obj["name"]:
        raise MQError("DISPLAY identity differs from the requested exact object")
    if typ == "queue":
        expected = obj["type"]
        if str(current.get("type", "")).lower() != expected:
            raise MQError("Existing queue type differs from declaration; conversion is refused")
    if obj["type"] == "channel" and obj["state"] == "present":
        if str(current.get("chltype", "")).lower() != obj["attributes"]["chltype"]:
            raise MQError("Existing channel type differs; conversion is refused")
    return current


def plan_object(obj, current):
    desired = obj["attributes"]
    if obj["state"] == "absent":
        delete_parameters = {}
        if obj["type"] == "channel" and current is not None:
            chltype = str(current.get("chltype", "")).lower()
            if chltype not in CHANNEL_TYPES:
                raise MQError("DISPLAY lacks a supported channel type required for safe deletion")
            # DELETE CHANNEL selects the repository table, not the DEFINE
            # channel type. CLNTCONN objects live in the client table; all
            # remaining supported types live in the queue-manager table.
            delete_parameters["chltable"] = "clntconn" if chltype == "clntconn" else "qmgr"
        return dict(action="delete" if current is not None else "none", parameters=delete_parameters,
                    before={"state": "present" if current is not None else "absent"}, after={"state": "absent"})
    if current is None:
        if obj["type"] == "topic" and not desired.get("topicstr"):
            raise MQError("Creating a topic requires topicstr")
        if obj["type"] == "channel" and desired["chltype"] in {"sdr", "clntconn", "clussdr"} and not desired.get("conname"):
            raise MQError("Creating this channel type requires conname")
        return dict(action="define", parameters=desired, before={"state": "absent"},
                    after=dict(state="present", attributes=desired))
    before, delta = {}, {}
    for key, value in desired.items():
        if key not in current:
            raise MQError("DISPLAY lacks declared attribute %s; unsupported platform/response" % key)
        before[key] = normalize(current[key], ATTRIBUTES[obj["type"]][key])
        if before[key] != value:
            if obj["type"] == "topic" and key == "topicstr":
                raise MQError("Changing topicstr requires a separately reviewed replacement; refused")
            delta[key] = value
    # CHLTYPE is immutable but required as a qualifier on ALTER CHANNEL.
    if delta and obj["type"] == "channel":
        delta["chltype"] = desired["chltype"]
    return dict(action="alter" if delta else "none", parameters=delta,
                before=dict(state="present", attributes=before), after=dict(state="present", attributes=desired))


def reconcile(client, objects, check_mode=False, allow_deletion=False):
    objects = validate_objects(objects, allow_deletion)
    # Complete input validation and discovery before the first mutation.
    plans = [dict(name=obj["name"], type=obj["type"], **plan_object(obj, discover(client, obj))) for obj in objects]
    changed = any(p["action"] != "none" for p in plans)
    applied = []
    if not check_mode:
        for obj, plan in zip(objects, plans):
            if plan["action"] == "none":
                continue
            try:
                responses(client.command(plan["action"], obj["type"], obj["name"], plan["parameters"]))
                applied.append(dict(name=obj["name"], type=obj["type"], action=plan["action"]))
                if plan_object(obj, discover(client, obj))["action"] != "none":
                    raise MQError("Post-change DISPLAY does not match desired state")
            except MQError as exc:
                # Changes are not transactional; timeouts can leave an unknown
                # outcome. Never automatically retry or roll back a mutation.
                exc.applied = applied
                exc.mutation_attempted = True
                raise
    return dict(changed=changed, plans=plans, applied=applied, verified=not check_mode,
                diff=[dict(before_header=p["type"] + ":" + p["name"], after_header=p["type"] + ":" + p["name"],
                           before=p["before"], after=p["after"]) for p in plans if p["action"] != "none"])
