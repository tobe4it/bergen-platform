"""No-write Paperless 3.3.0 ownerless group document visibility audit.

Always tests actual Django model-view permissions and permitted_document_ids,
not just explicit guardian ACL entries. Outputs aggregate counters only:
never document IDs, personal usernames, group assignments or OCR.
"""
import json
import sys

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from documents.models import Document
from documents.permissions import permitted_document_ids
from guardian.models import GroupObjectPermission
from paperless.version import __full_version_str__

FRAME = "BERGEN_PAPERLESS_CHAT_OWNERLESS_ACL_AUDIT_V1:"
MAX_INPUT = 256
MAX_DOCS = 5000
MAX_USERS = 300
PARENT = "Eltern@bergen.intern"
CHILD = "Kinder@bergen.intern"


def emit(status, **kwargs):
    data = {"AUDIT": "READ_ONLY", "STATUS": status,
            "CHANGED": False, "DOCUMENTS_CHANGED": False,
            "MODEL_INFERENCE": "NO", "USER_PERMISSIONS_CHANGED": False}
    data.update(kwargs)
    print(FRAME + json.dumps(data, sort_keys=True), flush=True)


def main():
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        request = json.loads(raw) if len(raw) <= MAX_INPUT else {}
        if (request != {"protocol": "native-chat-ownerless-acl-audit-v1"}
                or __full_version_str__ != "3.3.0"):
            return emit("BLOCKED")
        parent = Group.objects.filter(name=PARENT)
        if parent.count() != 1:
            return emit("PARENT_GROUP_UNREVIEWED")
        doc_type = ContentType.objects.get_for_model(Document)
        parent_grants = GroupObjectPermission.objects.filter(
            group=parent.first(), content_type=doc_type,
            permission__content_type=doc_type,
            permission__codename__in=("view_document", "change_document"),
        ).values_list("object_pk", flat=True)
        shared_ids = set()
        for value in parent_grants:
            if not value.isdecimal() or len(value) > 12:
                return emit("MALFORMED_ACL_REFERENCE")
            shared_ids.add(int(value))
            if len(shared_ids) > MAX_DOCS:
                return emit("BOUNDS_EXCEEDED")
        ownerless_shared = Document.objects.filter(
            pk__in=shared_ids, owner__isnull=True
        )
        total = ownerless_shared.count()
        if total > MAX_DOCS:
            return emit("BOUNDS_EXCEEDED")
        if User.objects.count() > MAX_USERS:
            return emit("BOUNDS_EXCEEDED")
        candidates = User.objects.filter(
            is_active=True, is_superuser=False,
        ).exclude(groups__name=PARENT).distinct()
        nonparent_model_viewers = 0
        affected_nonparent = 0
        child_model_viewers = 0
        child_affected = 0
        # The server's real ownerless visibility: intersect the selected
        # parent-granted ownerless docs with the user's actual view filter.
        for user in candidates:
            if not user.has_perm("documents.view_document"):
                continue
            nonparent_model_viewers += 1
            exposed = ownerless_shared.filter(
                pk__in=permitted_document_ids(user)
            ).count()
            affected_nonparent += exposed
            if user.groups.filter(name=CHILD).exists():
                child_model_viewers += 1
                child_affected += exposed
        state = (
            "CROSS_GROUP_VISIBILITY" if affected_nonparent
            else "NO_NONPARENT_CROSS_VISIBILITY_OBSERVED"
        )
        return emit("INSPECTED", FINDING=state,
                    OWNERLESS_PARENT_SHARED=total,
                    ACTIVE_NONPARENT_MODEL_VIEWERS=nonparent_model_viewers,
                    NONPARENT_VISIBLE_DOCUMENT_PAIRS=affected_nonparent,
                    CHILD_GROUP_MODEL_VIEWERS=child_model_viewers,
                    CHILD_GROUP_VISIBLE_DOCUMENT_PAIRS=child_affected,
                    CHAT_RELEASE_GATE="BLOCKED" if affected_nonparent
                    else "FURTHER_PER_USER_NEGATIVE_TEST_REQUIRED")
    except Exception:
        return emit("BLOCKED")


# Ansible shell appends main() after source.
