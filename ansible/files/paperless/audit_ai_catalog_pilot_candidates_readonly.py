#!/usr/bin/env python3
"""Read-only Paperless v3.3.0 pilot eligibility diagnosis.

Runs inside the already installed Paperless Django process, not in GitHub CI.
Never reads or prints OCR content, names, filenames, titles, or permissions.
Numeric document IDs are output only on explicit operator request and only
for owner/group/inbox/OCR/version-qualified candidate documents.
No inference, network call, ORM save, journal or backup write.
"""
import json
import sys

FRAME = "BERGEN_PAPERLESS_PILOT_SELECTION_V1:"
MAX_PILOT = 2
MAX_CANDIDATE_SCAN = 30
MAX_CANDIDATE_IDS = 8

REASONS = frozenset({
    "ELIGIBLE", "DOCUMENT_ABSENT", "OWNER_MISSING",
    "OWNER_INACTIVE", "OWNER_PRIVILEGED", "OWNER_OUTSIDE_PARENT_GROUP",
    "INBOX_TAG_MISSING", "OCR_INSUFFICIENT", "VERSIONED_DOCUMENT",
})


def valid_ids(value):
    return (isinstance(value, list) and len(value) <= MAX_PILOT
            and len(value) == len(set(str(x) for x in value))
            and all(type(x) is int and x > 0 for x in value))


def classify(doc, group):
    """Mirror the live production worker's eligibility predicates and order."""
    if doc is None:
        return "DOCUMENT_ABSENT"
    if doc.owner_id is None or doc.owner is None:
        return "OWNER_MISSING"
    if not doc.owner.is_active:
        return "OWNER_INACTIVE"
    if doc.owner.is_staff or doc.owner.is_superuser:
        return "OWNER_PRIVILEGED"
    if not doc.owner.groups.filter(pk=group.pk).exists():
        return "OWNER_OUTSIDE_PARENT_GROUP"
    if not doc.tags.filter(is_inbox_tag=True).exists():
        return "INBOX_TAG_MISSING"
    if not doc.content or len(doc.content.strip()) < 30:
        return "OCR_INSUFFICIENT"
    if doc.root_document_id is not None or doc.versions.exists():
        return "VERSIONED_DOCUMENT"
    return "ELIGIBLE"


def emit(**values):
    print(FRAME + json.dumps(
        dict(AUDIT="READ_ONLY", CHANGED=False, DOCUMENTS_CHANGED="NO",
             MODEL_INFERENCE="NO", **values), sort_keys=True), flush=True)


def main():
    try:
        raw = sys.stdin.read(2501)
        if len(raw) > 2500:
            emit(STATUS="INPUT_REJECTED")
            return
        request = json.loads(raw)
        if (not isinstance(request, dict)
                or request.get("protocol") != "pilot-selection-v1"
                or not valid_ids(request.get("pilot_ids"))
                or type(request.get("show_candidate_ids")) is not bool):
            emit(STATUS="INPUT_REJECTED")
            return
        group_name = request.get("allowed_group")
        if (not isinstance(group_name, str) or not (1 <= len(group_name) <= 150)
                or "@" not in group_name):
            emit(STATUS="INPUT_REJECTED")
            return

        # Import only after envelope validation, so offline tests can load
        # the pure eligibility classifier without a Django installation.
        from django.contrib.auth.models import Group
        from documents.models import Document
        from paperless.version import __full_version_str__

        if __full_version_str__ != "3.3.0":
            emit(STATUS="VERSION_UNREVIEWED")
            return
        groups = Group.objects.filter(name=group_name)
        if groups.count() != 1:
            emit(STATUS="GROUP_UNREVIEWED")
            return
        group = groups.first()

        selected = []
        for identifier in request["pilot_ids"]:
            doc = Document.objects.filter(pk=identifier).select_related("owner").first()
            reason = classify(doc, group)
            if reason not in REASONS:
                raise ValueError("INVALID_REASON")
            selected.append(reason)

        # Match the catalogue worker's source queryset and its 30-row scan
        # bound; do not enumerate other users' document IDs or metadata.
        candidates = Document.objects.filter(
            tags__is_inbox_tag=True,
            owner__groups=group,
            owner__is_active=True,
        ).distinct().select_related("owner").order_by("pk")[:MAX_CANDIDATE_SCAN]
        eligible_ids = [
            doc.pk for doc in candidates if classify(doc, group) == "ELIGIBLE"
        ][:MAX_CANDIDATE_IDS]

        result = dict(STATUS="INSPECTED",
                      PILOT_SELECTION_COUNT=len(selected),
                      PILOT_ELIGIBILITY=selected,
                      ELIGIBLE_CANDIDATE_COUNT_SHOWN=len(eligible_ids),
                      CANDIDATE_SCAN_BOUND=MAX_CANDIDATE_SCAN,
                      IDS_INCLUDED=request["show_candidate_ids"])
        if request["show_candidate_ids"]:
            # The user explicitly requested concrete choices; emit only
            # positive numeric IDs, never titles, OCR, owners, or metadata.
            result["ELIGIBLE_CANDIDATE_IDS"] = eligible_ids
        emit(**result)
    except Exception:
        emit(STATUS="UNVERIFIED")

