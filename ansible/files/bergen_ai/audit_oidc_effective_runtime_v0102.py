"""Open WebUI v0.10.2 tokenless, stdlib-only OIDC env source audit.

Open WebUI 0.10.2 uses the environment defaults when
ENABLE_OAUTH_PERSISTENT_CONFIG=false; we can establish the process environment
without importing the heavy application module in a second Python process.
The active app's in-memory Config.DEFAULTS could still have been changed by
an authenticated admin API call. This audit CANNOT prove effective live config
or a successful OAuth callback; it explicitly labels such facts unmeasured.
Never print actual values of identity, group names, secrets, or OIDC claims.
"""
import json
import os

FRAME = "BERGEN_OIDC_EFFECTIVE_RUNTIME_V1:"


class Reject(Exception):
    pass


def flag(var, default="false"):
    v = os.environ.get(var, default).lower()
    if v not in ("true", "false"):
        raise Reject("FLAG_FORMAT_UNREVIEWED")
    return "ON" if v == "true" else "OFF"


def main():
    persistence = flag("ENABLE_OAUTH_PERSISTENT_CONFIG")
    if persistence != "OFF":
        raise Reject("OAUTH_PERSISTENCE_NOT_COVERED")
    try:
        blocked = json.loads(os.environ.get("OAUTH_BLOCKED_GROUPS", "[]"))
    except (ValueError, TypeError):
        raise Reject("BLOCKED_GROUPS_FORMAT_UNREVIEWED") from None
    if not isinstance(blocked, list):
        raise Reject("BLOCKED_GROUPS_FORMAT_UNREVIEWED")
    blocked_status = "EMPTY" if blocked == [] else "NONEMPTY"

    mapping = flag("ENABLE_OAUTH_GROUP_MANAGEMENT")
    role = flag("ENABLE_OAUTH_ROLE_MANAGEMENT")
    creation = flag("ENABLE_OAUTH_GROUP_CREATION")
    claim = os.environ.get("OAUTH_GROUPS_CLAIM",
                           os.environ.get("OAUTH_GROUP_CLAIM", "groups"))
    default_role = os.environ.get("DEFAULT_USER_ROLE", "pending")
    # Claim and role values are classified, never printed verbatim.
    print(FRAME + json.dumps({
        "AUDIT": "READ_ONLY",
        "CHANGED": False,
        "CONFIG_BASIS": "RUNNING_CONTAINER_ENV_V0_10_2",
        "GROUP_MANAGEMENT_ENV": mapping,
        "GROUP_MANAGEMENT_SOURCE": mapping,
        "GROUP_CREATION_SOURCE": creation,
        "ROLE_MANAGEMENT_SOURCE": role,
        "PERSISTENT_OAUTH_CONFIG": persistence,
        "GROUP_CLAIM": "GROUPS" if claim == "groups" else "OTHER",
        "BLOCKED_GROUPS": blocked_status,
        "DEFAULT_USER_ROLE": "PENDING" if default_role == "pending" else "OTHER",
        "IN_PROCESS_EFFECTIVE_CONFIG": "NOT_MEASURED",
        "OIDC_CALLBACK_OBSERVED": "NOT_MEASURED",
        "OIDC_GROUP_CLAIMS_OBSERVED": "NOT_MEASURED",
        "MEMBERSHIP_WRITE_OBSERVED": "NOT_MEASURED"
    }, sort_keys=True), flush=True)


try:
    main()
except Reject as failure:
    print(FRAME + json.dumps({
        "AUDIT": "FAILED_CLOSED",
        "STATUS": str(failure),
        "CHANGED": False
    }, sort_keys=True), flush=True)
    raise SystemExit(2) from None
except Exception:
    print(FRAME + json.dumps({
        "AUDIT": "FAILED_CLOSED",
        "STATUS": "UNEXPECTED_RUNTIME_FAILURE",
        "CHANGED": False
    }, sort_keys=True), flush=True)
    raise SystemExit(2) from None
