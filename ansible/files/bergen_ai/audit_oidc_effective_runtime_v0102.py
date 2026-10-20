"""Tokenless read-only effective Open WebUI v0.10.2 OAuth runtime checks.

Executed INSIDE the existing open-webui container, using its own runtime
Config resolution code. It does not request/print login tokens, claims,
client secrets, user identifiers or group names, and has no write operations.
"""
import asyncio
import json
import os

FRAME = "BERGEN_OIDC_EFFECTIVE_RUNTIME_V1:"


class AuditFailure(Exception):
    """Only the predetermined stage code may leave this process."""


async def check():
    try:
        from open_webui.models.config import Config
        from open_webui.utils.oauth import get_oauth_runtime_config
    except Exception:
        raise AuditFailure("MODULE_IMPORT_FAILED") from None

    try:
        cfg = await get_oauth_runtime_config()
    except Exception:
        raise AuditFailure("RUNTIME_CONFIG_RESOLUTION_FAILED") from None
    block = cfg.OAUTH_BLOCKED_GROUPS
    try:
        blocked = json.loads(block)
        block_state = ("EMPTY" if blocked == [] else "NONEMPTY"
                       if isinstance(blocked, list) else "UNREVIEWED")
    except (TypeError, ValueError):
        block_state = "UNREVIEWED"
    result = {
        "AUDIT": "READ_ONLY",
        "CHANGED": False,
        "GROUP_MANAGEMENT_ENV": "ON" if os.getenv(
            "ENABLE_OAUTH_GROUP_MANAGEMENT", "").lower() == "true" else "OFF",
        "GROUP_MANAGEMENT_EFFECTIVE": "ON"
        if cfg.ENABLE_OAUTH_GROUP_MANAGEMENT is True else "OFF",
        "GROUP_CREATION_EFFECTIVE": "ON"
        if cfg.ENABLE_OAUTH_GROUP_CREATION is True else "OFF",
        "ROLE_MANAGEMENT_EFFECTIVE": "ON"
        if cfg.ENABLE_OAUTH_ROLE_MANAGEMENT is True else "OFF",
        "PERSISTENT_OAUTH_CONFIG": "ON"
        if Config.OAUTH_PERSISTENT_ENABLED else "OFF",
        "GROUP_CLAIM": "GROUPS" if cfg.OAUTH_GROUPS_CLAIM == "groups"
        else "OTHER",
        "BLOCKED_GROUPS": block_state,
        "DEFAULT_USER_ROLE": "PENDING" if cfg.DEFAULT_USER_ROLE == "pending"
        else "OTHER",
        "OIDC_CALLBACK_OBSERVED": "NOT_MEASURED",
        "OIDC_GROUP_CLAIMS_OBSERVED": "NOT_MEASURED",
        "MEMBERSHIP_WRITE_OBSERVED": "NOT_MEASURED",
    }
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


try:
    asyncio.run(check())
except AuditFailure as failure:
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
