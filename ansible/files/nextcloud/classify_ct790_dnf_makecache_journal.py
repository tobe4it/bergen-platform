#!/usr/bin/env python3
"""Classify bounded dnf-makecache journal text without returning any log content.

Run on the already verified PVE host with journal text passed only through stdin.
Never emit repository URLs, error messages, internal hostnames or guest data.
"""
import json
import re
import sys

MAX_BYTES = 32768
MAX_LINES = 80

PATTERNS = {
    "dns": re.compile(
        r"could(?:n't| not) resolve|name or service not known|"
        r"temporary failure in name resolution|curl error\s*\(6\)",
        re.IGNORECASE),
    "connection": re.compile(
        r"network is unreachable|no route to host|connection refused|"
        r"failed to connect|could(?:n't| not) connect|"
        r"curl error\s*\((?:7|28)\)|timed? out",
        re.IGNORECASE),
    "repository_metadata": re.compile(
        r"failed to download metadata|cannot download repomd|"
        r"cannot prepare internal mirrorlist|errors during downloading metadata|"
        r"cannot find a valid baseurl|no urls in mirrorlist",
        re.IGNORECASE),
    "repository_configuration": re.compile(
        r"no enabled repositories|no repositories available|"
        r"error parsing config|is listed more than once|"
        r"not a valid repository id",
        re.IGNORECASE),
}

def classify(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("JOURNAL_BOUNDS_EXCEEDED")
    try:
        journal = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("JOURNAL_NOT_UTF8") from exc
    lines = [line for line in journal.splitlines() if line.strip()]
    if len(lines) > MAX_LINES:
        raise ValueError("JOURNAL_LINES_EXCEEDED")
    flags = {name: bool(pattern.search(journal))
             for name, pattern in PATTERNS.items()}
    if flags["dns"]:
        category = "DNS_RESOLUTION_ERROR_OBSERVED"
    elif flags["connection"]:
        category = "NETWORK_CONNECTION_ERROR_OBSERVED"
    elif flags["repository_configuration"]:
        category = "REPOSITORY_CONFIG_ERROR_OBSERVED"
    elif flags["repository_metadata"]:
        category = "REPOSITORY_METADATA_ERROR_OBSERVED_CAUSE_UNDETERMINED"
    else:
        category = "NO_RECOGNIZED_CAUSE_IN_BOUNDED_JOURNAL"
    return {
        "result": "ROCKY_9_8_CT790_DNF_JOURNAL_CLASSIFIED_READ_ONLY",
        "category": category,
        "bounded_journal_lines": len(lines),
        "dns_error_observed": flags["dns"],
        "network_error_observed": flags["connection"],
        "repo_metadata_error_observed": flags["repository_metadata"],
        "repo_config_error_observed": flags["repository_configuration"],
        "raw_content_disclosed": False,
        "files_written": 0,
        "services_changed": 0,
        "guest_started_or_stopped": False,
    }

def main():
    try:
        result = classify(sys.stdin.buffer.read(MAX_BYTES + 1))
        print(json.dumps(result, sort_keys=True))
    except ValueError as exc:
        print(json.dumps({
            "result": "ROCKY_9_8_CT790_DNF_JOURNAL_READ_ONLY_BLOCKED",
            "reason": str(exc), "raw_content_disclosed": False,
            "files_written": 0,
        }, sort_keys=True))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
