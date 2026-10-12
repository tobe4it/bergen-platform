#!/usr/bin/env python3
"""Offline allowlist validation for proposed Synology -> Paperless scan routes.

No filesystem access, networking, imports, or configuration changes are made.
A passing result does NOT attest to NAS ACLs, Paperless users, or workflows.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import PurePosixPath

import yaml


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
USERNAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
RESERVED_USERS = {"admin", "anonymoususer"}


def _absolute_path(raw: object) -> str:
    if not isinstance(raw, str) or not raw.startswith("/"):
        raise ValueError("source_path must be an absolute POSIX path")
    parts = raw.split("/")[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("source_path must not contain empty, . or .. components")
    path = str(PurePosixPath(raw))
    if path == "/srv/bergen-paperless" or path.startswith("/srv/bergen-paperless/"):
        raise ValueError("source_path must be a NAS staging mount, not Paperless storage")
    return path


def validate(config: object) -> dict[str, int]:
    """Validate explicit route ownership before implementing any file movement."""
    if not isinstance(config, dict) or set(config) != {"sources"}:
        raise ValueError("configuration must contain exactly one key: sources")
    sources = config["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a nonempty list")

    ids: set[str] = set()
    paths: list[str] = []
    targets: set[str] = set()
    counts = {"private": 0, "group": 0}
    shared: set[str] = set()

    for number, item in enumerate(sources, 1):
        if not isinstance(item, dict) or set(item) != {
            "id", "source_path", "consume_subdir", "scope", "principal"
        }:
            raise ValueError(f"route {number} must have exactly the five required fields")

        route_id = item["id"]
        if not isinstance(route_id, str) or not IDENTIFIER.fullmatch(route_id):
            raise ValueError(f"route {number} has invalid id")
        if route_id.casefold() in ids:
            raise ValueError(f"route {number} has duplicate id")
        ids.add(route_id.casefold())

        source = _absolute_path(item["source_path"])
        if source.casefold() in paths:
            raise ValueError(f"route {number} has duplicate source_path")
        for previous in paths:
            if (source.casefold().startswith(previous + "/") or
                    previous.startswith(source.casefold() + "/")):
                raise ValueError(f"route {number} overlaps another source_path")
        paths.append(source.casefold())

        scope, principal, dest = item["scope"], item["principal"], item["consume_subdir"]
        if not isinstance(scope, str) or scope not in counts:
            raise ValueError(f"route {number} has unknown scope")
        if not isinstance(principal, str) or not isinstance(dest, str):
            raise ValueError(f"route {number} has invalid principal or consume_subdir")

        if scope == "private":
            if (not USERNAME.fullmatch(principal) or
                    principal.casefold() in RESERVED_USERS):
                raise ValueError(f"route {number} has invalid private principal")
            if dest != f"Privat/{principal}":
                raise ValueError(f"route {number} private target must match principal")
        else:
            if principal not in {"Eltern", "Familie"} or dest != principal:
                raise ValueError(f"route {number} has invalid group route")
            if principal in shared:
                raise ValueError(f"route {number} repeats a shared group")
            shared.add(principal)

        if dest.casefold() in targets:
            raise ValueError(f"route {number} has duplicate consume_subdir")
        targets.add(dest.casefold())
        counts[scope] += 1

    if shared != {"Eltern", "Familie"}:
        raise ValueError("exactly one route for each shared group is required")
    if counts["private"] < 1:
        raise ValueError("at least one private user route is required")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Git-ignored mapping YAML to validate offline")
    args = parser.parse_args()

    try:
        with open(args.config, encoding="utf-8") as stream:
            result = validate(yaml.safe_load(stream))
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"PREFLIGHT_FAIL: {exc}", file=sys.stderr)
        return 1

    print("PREFLIGHT_PASS: route syntax and isolation checks only")
    print(f"private_routes={result['private']} shared_routes={result['group']}")
    print("NOT VERIFIED: NAS permissions, mounts, user/group existence, or Paperless ACLs")
    print("LIVE_INGESTION=DISABLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
