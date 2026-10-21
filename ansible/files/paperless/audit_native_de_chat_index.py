"""Read-only Paperless 3.3.0 German document-chat index readiness.

No vector-store access (which could create index paths or lock files), no
database/document writes, no inference. Output only aggregate counters.
This is a separate validation from the existing Bergen AI catalog journal.
"""
import json
import stat
import sys
from pathlib import Path

from paperless.config import AIConfig
from paperless.version import __full_version_str__
from documents.models import Document, PaperlessTask

FRAME = "BERGEN_PAPERLESS_NATIVE_CHAT_INDEX_AUDIT_V1:"
MAX_INPUT = 256


def emit(status, **fields):
    result = {
        "AUDIT": "READ_ONLY",
        "STATUS": status,
        "CHANGED": False,
        "INDEX_CHANGED": False,
        "DOCUMENTS_CHANGED": False,
        "MODEL_INFERENCE": "NO",
    }
    result.update(fields)
    print(FRAME + json.dumps(result, sort_keys=True), flush=True)


def main():
    try:
        data = sys.stdin.read(MAX_INPUT + 1)
        req = json.loads(data) if len(data) <= MAX_INPUT else {}
        if (req != {"protocol": "native-de-chat-index-audit-v1"}
                or __full_version_str__ != "3.3.0"):
            return emit("BLOCKED")
        # Deliberately no AIConfig().llm_index_exists() or get_vector_store():
        # those helpers create missing index directories / SQLite locks.
        from django.conf import settings

        ai = AIConfig()
        model = ai.llm_embedding_model
        configured = (
            ai.ai_enabled is True
            and ai.llm_output_language == "de"
            and ai.llm_backend == "ollama"
            and ai.llm_embedding_backend == "ollama"
            and model in ("bge-m3", "bge-m3:latest")
            and ai.llm_allow_internal_endpoints is True
        )
        if not configured:
            return emit("CONFIG_NOT_READY")
        index_dir = Path(settings.LLM_INDEX_DIR)
        index_file = index_dir / "llmindex.db"
        if index_dir.is_symlink() or index_file.is_symlink():
            return emit("UNREVIEWED_INDEX_PATH")
        present = index_file.exists()
        if present and not stat.S_ISREG(index_file.stat().st_mode):
            return emit("UNREVIEWED_INDEX_PATH")
        size = index_file.stat().st_size if present else 0
        if size < 0:
            return emit("BLOCKED")
        index_state = "PRESENT_NOT_COVERAGE_VERIFIED" if present else "ABSENT"
        pending = PaperlessTask.objects.filter(
            task_type=PaperlessTask.TaskType.LLM_INDEX,
            status__in=(PaperlessTask.Status.PENDING, PaperlessTask.Status.STARTED),
        ).count()
        failed = PaperlessTask.objects.filter(
            task_type=PaperlessTask.TaskType.LLM_INDEX,
            status=PaperlessTask.Status.FAILURE,
        ).count()
        return emit(
            "INSPECTED",
            OUTPUT_LANGUAGE="DE",
            GENERATION_BACKEND="OLLAMA",
            EMBEDDINGS="LOCAL_BGE_M3",
            INDEX_FILE=index_state,
            INDEX_BYTES=size,
            TOTAL_DOCUMENTS=Document.objects.count(),
            INDEX_TASKS_ACTIVE=pending,
            INDEX_TASKS_FAILED=failed,
            INDEX_COVERAGE="NOT_PROVEN",
        )
    except Exception:
        return emit("BLOCKED")


# Executed only by approved ansible playbook: main()
