"""Read-only Paperless-ngx 3.3 taxonomy visibility audit after human reclassification.

Read only the persisted post-AI journal snapshot for the exact, explicitly
provided reference document (ID 10), current taxonomy assignment and up to
six exact reviewed target IDs. Do not emit titles, tag/type names, owner IDs,
OCR content, journal JSON, permissions object IDs or raw exception text.

Identifies categories added to the reference document *after* AI processing;
compares their native Paperless object-level VIEW visibility for each target
document owner using permitted_object_ids, the same security primitive as
the classifier's taxonomy name matching. Does not run the LLM.
"""
import json
from pathlib import Path
import sqlite3
import stat
import sys

FRAME = "BERGEN_PAPERLESS_TAXONOMY_VISIBILITY_V1:"
JOURNAL = Path("/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3")
MAX_TARGETS = 6


def emit(**values):
    print(FRAME + json.dumps(
        dict(AUDIT="READ_ONLY", CHANGED=False, MODEL_INFERENCE="NO",
             DOCUMENTS_CHANGED="NO", **values), sort_keys=True), flush=True)


def valid_request(r):
    if not isinstance(r, dict) or set(r) != {
        "protocol", "reference_id", "target_ids",
    }:
        return False
    ids = r.get("target_ids")
    return (r.get("protocol") == "taxonomy-visibility-v1"
            and type(r.get("reference_id")) is int
            and r["reference_id"] == 10
            and isinstance(ids, list) and 1 <= len(ids) <= MAX_TARGETS
            and all(type(i) is int and i > 0 and i != 10 for i in ids)
            and len(set(ids)) == len(ids))


def manual_changes(after, current_type_id, current_tag_ids, expected_id):
    """Compare journal's post-AI state to the current document assignment."""
    if (not isinstance(after, dict)
            or type(after.get("id")) is not int
            or after["id"] != expected_id
            or not isinstance(after.get("tag_ids"), list)
            or any(type(x) is not int or x <= 0 for x in after["tag_ids"])
            or type(current_type_id) not in (int, type(None))
            or any(type(x) is not int or x <= 0 for x in current_tag_ids)):
        raise ValueError("POSTIMAGE_UNVERIFIED")
    added = sorted(set(current_tag_ids) - set(after["tag_ids"]))
    removed = sorted(set(after["tag_ids"]) - set(current_tag_ids))
    return (after.get("document_type_id") != current_type_id,
            added, removed)


def viewable_ids(user, model, permission, ids):
    """Honor current object permissions, not same-owner guesses or group names."""
    from documents.permissions import permitted_object_ids
    if not ids:
        return set()
    allowed = permitted_object_ids(user, model, permission)
    return set(model.objects.filter(pk__in=ids).filter(
        pk__in=allowed).values_list("pk", flat=True))


def main():
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            emit(STATUS="INPUT_REJECTED")
            return
        request = json.loads(raw)
        if not valid_request(request):
            emit(STATUS="INPUT_REJECTED")
            return

        from paperless.version import __full_version_str__
        from documents.models import Document, DocumentType, Tag
        if __full_version_str__ != "3.3.0":
            emit(STATUS="VERSION_UNREVIEWED")
            return

        if JOURNAL.parent.is_symlink() or JOURNAL.is_symlink():
            emit(STATUS="JOURNAL_UNSAFE")
            return
        if not stat.S_ISREG(JOURNAL.stat().st_mode):
            emit(STATUS="JOURNAL_UNVERIFIED")
            return

        with sqlite3.connect("file:" + str(JOURNAL) + "?mode=ro",
                             uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT state,after_json FROM catalogue WHERE document_id=?",
                (request["reference_id"],),
            ).fetchall()
        if len(rows) != 1 or rows[0][0] != "APPLIED" or not rows[0][1]:
            emit(STATUS="REFERENCE_JOURNAL_UNVERIFIED")
            return

        ref = Document.objects.filter(
            pk=request["reference_id"]).select_related("owner").first()
        if ref is None or ref.owner_id is None:
            emit(STATUS="REFERENCE_DOCUMENT_UNVERIFIED")
            return

        current_tags = list(ref.tags.values_list("id", flat=True))
        type_changed, added_tags, removed_tags = manual_changes(
            json.loads(rows[0][1]),
            ref.document_type_id,
            current_tags,
            request["reference_id"],
        )
        if len(added_tags) > 8 or len(removed_tags) > 8:
            emit(STATUS="REFERENCE_TAG_DIFF_UNREVIEWED")
            return

        # The name check only verifies the user-supplied category name.
        # It does not disclose any type or tag name in the report.
        type_is_cert = bool(ref.document_type_id
            and DocumentType.objects.filter(
                pk=ref.document_type_id, name__iexact="Zertifikat").exists())

        results = []
        for target_id in request["target_ids"]:
            target = Document.objects.filter(
                pk=target_id).select_related("owner").first()
            if target is None or target.owner is None:
                results.append(dict(
                    document_id=target_id, OWNER="ABSENT",
                    TYPE_VISIBLE="NOT_CHECKED", ADDED_TAGS_VISIBLE="NOT_CHECKED",
                ))
                continue
            type_allowed = (viewable_ids(
                target.owner, DocumentType, "view_documenttype",
                [ref.document_type_id] if ref.document_type_id else []
            ) if ref.document_type_id else set())
            tags_allowed = viewable_ids(
                target.owner, Tag, "view_tag", added_tags
            )
            results.append(dict(
                document_id=target_id,
                OWNER="SAME" if target.owner_id == ref.owner_id else "DIFFERENT",
                TYPE_VISIBLE="YES" if ref.document_type_id in type_allowed else "NO",
                ADDED_TAGS_VISIBLE=f"{len(tags_allowed)}/{len(added_tags)}",
            ))

        emit(
            STATUS="INSPECTED",
            REFERENCE_STATE="APPLIED",
            POST_AI_TYPE_CHANGED=type_changed,
            REFERENCE_TYPE_IS_ZERTIFIKAT=type_is_cert,
            POST_AI_TAGS_ADDED_COUNT=len(added_tags),
            POST_AI_TAGS_REMOVED_COUNT=len(removed_tags),
            TARGET_SCOPE_COUNT=len(results), TARGET_VISIBILITY=results,
        )
    except Exception:
        emit(STATUS="UNVERIFIED")


# Appended main() call via Django shell -c, explicitly under Ansible gate.
