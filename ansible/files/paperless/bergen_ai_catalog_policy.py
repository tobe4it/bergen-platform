"""Policy primitives for Paperless-ngx 3.3.0 Bergen inbox AI cataloguing.

No Django imports, no network access, no secrets and no side effects. The
runtime validates these decisions again after the slow Ollama inference.
"""
import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


class PolicyError(Exception):
    pass


def demand(condition, code):
    if not condition:
        raise PolicyError(code)


def import_title(title, original_filename):
    """Only overwrite clearly machine-imported filename titles, never human titles."""
    if not isinstance(title, str) or not isinstance(original_filename, str):
        return False
    stem = Path(original_filename).stem.strip()
    normalized = title.strip().casefold()
    return bool(stem) and normalized in (stem.casefold(), Path(original_filename).name.casefold())


def safe_endpoint(endpoint):
    """No hosted LLM and no SSRF-enabled arbitrary URL. DNS validated by runtime."""
    if not isinstance(endpoint, str) or len(endpoint) > 240:
        return False
    try:
        parts = urlsplit(endpoint)
        if parts.scheme != "http" or not parts.hostname or parts.username or parts.password:
            return False
        if parts.query or parts.fragment or parts.path not in ("", "/"):
            return False
        if parts.port != 11434:
            return False
        host = parts.hostname.lower()
        if host in {"localhost", "ollama", "bergen-ai", "127.0.0.1", "::1"}:
            return True
        if host.endswith(".intern") or host.endswith(".internal"):
            return True
        addr = ipaddress.ip_address(host)
        return addr.is_private and not addr.is_link_local and not addr.is_unspecified
    except (ValueError, TypeError):
        return False


def stable_snapshot(data):
    """Current document fields for optimistic concurrency; no OCR contents stored."""
    required = {"id", "owner_id", "title", "original_filename",
                "correspondent_id", "document_type_id", "storage_path_id",
                "created", "modified", "checksum", "content_sha256", "tag_ids",
                "inbox"}
    demand(isinstance(data, dict) and set(data) == required, "SNAPSHOT_INVALID")
    demand(type(data["id"]) is int and data["id"] > 0, "SNAPSHOT_INVALID")
    demand(type(data["owner_id"]) is int and data["owner_id"] > 0, "SNAPSHOT_INVALID")
    demand(type(data["inbox"]) is bool, "SNAPSHOT_INVALID")
    demand(isinstance(data["tag_ids"], list)
           and all(type(i) is int and i > 0 for i in data["tag_ids"]),
           "SNAPSHOT_INVALID")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(data):
    return hashlib.sha256(stable_snapshot(data).encode()).hexdigest()


def plan_changes(current, suggestions, tags, correspondent_id, document_type_id):
    """Return only whitelisted metadata candidates, never owner/ACL/inbox edits."""
    demand(current["inbox"], "INBOX_REMOVED")
    demand(isinstance(suggestions, dict), "SUGGESTIONS_INVALID")
    title = suggestions.get("title")
    demand(isinstance(title, str), "SUGGESTIONS_INVALID")
    demand(isinstance(tags, list) and all(type(i) is int and i > 0 for i in tags),
           "TAGS_INVALID")
    prev_tags = set(current["tag_ids"])
    tag_ids = sorted(set(tags) - prev_tags)
    changes = {"title": None, "correspondent_id": None,
               "document_type_id": None, "add_tag_ids": tag_ids}
    new_title = title.strip()[:128]
    if new_title and import_title(current["title"], current["original_filename"]):
        if new_title != current["title"]:
            changes["title"] = new_title
    if current["correspondent_id"] is None and correspondent_id is not None:
        demand(type(correspondent_id) is int and correspondent_id > 0, "CORRESPONDENT_INVALID")
        changes["correspondent_id"] = correspondent_id
    if current["document_type_id"] is None and document_type_id is not None:
        demand(type(document_type_id) is int and document_type_id > 0, "DOCUMENT_TYPE_INVALID")
        changes["document_type_id"] = document_type_id
    return changes


def has_metadata_changes(changes):
    """Pure decision: valid classification with empty diff is not a failed job."""
    demand(isinstance(changes, dict) and set(changes) ==
           {"title", "correspondent_id", "document_type_id", "add_tag_ids"},
           "CHANGES_INVALID")
    return bool(changes["title"] is not None
                or changes["correspondent_id"] is not None
                or changes["document_type_id"] is not None
                or changes["add_tag_ids"])


def bounded_ai_labels(values):
    """Untrusted model names for one owner's human-readable Paperless note only.

    Never store OCR, prompt, model JSON, unrelated owner metadata, or arbitrary
    multiline output. Reject schema violations rather than copying them.
    """
    demand(isinstance(values, list) and len(values) <= 12,
           "NOTE_SUGGESTIONS_INVALID")
    out = []
    for value in values:
        demand(isinstance(value, str) and len(value) <= 128,
               "NOTE_SUGGESTIONS_INVALID")
        clean = " ".join(value.split())
        demand(all(ord(c) >= 32 and ord(c) != 127 for c in clean),
               "NOTE_SUGGESTIONS_INVALID")
        if clean and clean.casefold() not in [x.casefold() for x in out]:
            out.append(clean)
        demand(len(out) <= 6, "NOTE_SUGGESTIONS_INVALID")
    return out


def review_note_text(suggestions, resolved_type_name=None,
                     resolved_tag_names=None):
    """Compact, explicitly non-authoritative local AI note; no OCR in it.

    Group labels describe original LLM names, not authorization to create
    new taxonomy objects. Resolved labels must be the owner's visible ones.
    """
    demand(isinstance(suggestions, dict), "NOTE_SUGGESTIONS_INVALID")
    choices = suggestions.get("document_types")
    tags = suggestions.get("tags")
    demand(isinstance(choices, dict) and isinstance(tags, dict),
           "NOTE_SUGGESTIONS_INVALID")
    type_names = bounded_ai_labels(choices.get("new_names"))
    tag_names = bounded_ai_labels(tags.get("new_names"))
    visible_type = bounded_ai_labels(
        [resolved_type_name] if resolved_type_name is not None else [])
    visible_tags = bounded_ai_labels(
        resolved_tag_names if resolved_tag_names is not None else [])
    lines = [
        "Bergen-AI | Vorschlaege zur manuellen Pruefung",
        "Nicht freigegebene KI-Vorschlaege; keine neuen Kategorien angelegt.",
        "LLM-Dokumenttyp: " + (", ".join(type_names) or "(kein Namensvorschlag)"),
        "LLM-Tags: " + (", ".join(tag_names) or "(keine Namensvorschlaege)"),
        "Bestehender zugeordneter Typ: "
        + (", ".join(visible_type) or "(keiner)"),
        "Bestehende zugeordnete Tags: "
        + (", ".join(visible_tags) or "(keine)"),
        "Bitte pruefen und erst danach das Posteingangs-Tag entfernen.",
    ]
    result = "\n".join(lines)
    demand(len(result) <= 2048, "NOTE_SUGGESTIONS_INVALID")
    return result
