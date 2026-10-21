"""Only non-identifying Paperless-ngx v3.3 runtime inventory for Issue #113.

Executed through manage.py shell -c on the existing app instance. Absolutely no
Django model writes, changes to global AI, user roles, documents or tags.
Never output user/group names, document IDs, OCR contents or private endpoints.
"""
import json
import re
from django.contrib.auth.models import Group, User
from django.conf import settings
from documents.models import Document, Tag
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
from paperless.version import __full_version_str__

FRAME = "BERGEN_AI_CATALOG_PREFLIGHT_PAPERLESS_V1:"


def safe_model(name):
    if name and re.fullmatch(r"[A-Za-z0-9._:/-]{1,96}", name):
        return name
    return "NOT_SET_OR_UNREVIEWED"


def run():
    config_rows = ApplicationConfiguration.objects.count()
    report = {
        "AUDIT": "READ_ONLY",
        "VERSION": __full_version_str__,
        "CONFIG_ROWS": min(config_rows, 2),
        "TOTAL_INBOX_TAGS": Tag.objects.filter(is_inbox_tag=True).count(),
        "INBOX_DOCUMENTS": Document.objects.filter(
            tags__is_inbox_tag=True).distinct().count(),
        "PARENT_GROUPS": Group.objects.filter(
            name__startswith="Eltern@").count(),
        "FAMILY_GROUPS": Group.objects.filter(
            name__startswith="Familie@").count(),
        "CHILD_GROUPS": Group.objects.filter(
            name__startswith="Kinder@").count(),
        "PARENT_ACTIVE_NONSTAFF_ACCOUNTS": User.objects.filter(
            groups__name__startswith="Eltern@",
            is_active=True, is_staff=False, is_superuser=False,
        ).distinct().count(),
        "PARENT_OWNED_INBOX_WITH_OCR": Document.objects.filter(
            owner__groups__name__startswith="Eltern@",
            owner__is_active=True, owner__is_staff=False,
            owner__is_superuser=False,
            tags__is_inbox_tag=True, content_length__gte=30,
        ).distinct().count(),
        "CHANGED": False,
    }
    if config_rows == 1:
        c = AIConfig()
        report.update({
            "GLOBAL_AI": "ON" if c.ai_enabled else "OFF",
            "EMBEDDINGS": "ON" if c.llm_embedding_backend else "OFF",
            "LLM_BACKEND": (
                "OLLAMA" if c.llm_backend == "ollama" else
                "NOT_CONFIGURED" if not c.llm_backend else
                "OTHER"),
            "MODEL": safe_model(c.llm_model),
            "ENDPOINT": "CONFIGURED" if c.llm_endpoint else "NOT_CONFIGURED",
            "PRIVATE_LLM_ALLOWED": bool(c.llm_allow_internal_endpoints),
        })
    else:
        report.update({
            "GLOBAL_AI": "NOT_INSPECTED",
            "EMBEDDINGS": "NOT_INSPECTED",
            "LLM_BACKEND": "NOT_INSPECTED",
            "MODEL": "NOT_INSPECTED",
            "ENDPOINT": "NOT_INSPECTED",
            "PRIVATE_LLM_ALLOWED": False,
        })
    print(FRAME + json.dumps(report, sort_keys=True))


run()
