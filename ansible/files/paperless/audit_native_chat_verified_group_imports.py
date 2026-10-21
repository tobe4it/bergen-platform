"""No-write import-source inventory for the Bergen Paperless group chat ACL gate.

Runs ONLY inside the reviewed Paperless CT126 guest, OUTSIDE its Podman
container. Reuses the installed reconciler's exact receipt parser / live
Django checksum-owner-ACL verifier. Sends document IDs to Ansible privately
(no_log); only aggregate counts may be displayed at the very end of the
separate Django security audit. NEVER writes receipts, PDFs or document DB.
"""
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

FRAME = "BERGEN_CHAT_GROUP_IMPORT_PROOF_V1:"
MODULE = Path("/usr/local/libexec/bergen-paperless-reconcile-ingest.py")
MAX_RECEIPTS = 10000
MAX_MATCHES = 5000
SCOPES = {"Eltern": "Eltern@bergen.intern",
          "Familie": "Familie@bergen.intern"}


def emit(status, **kwargs):
    print(FRAME + json.dumps({"STATUS": status, "CHANGED": False,
          "DOCUMENTS_CHANGED": False, **kwargs}, sort_keys=True), flush=True)


def main():
    try:
        if os.geteuid() != 0 or MODULE.is_symlink() or not MODULE.is_file():
            return emit("BLOCKED")
        st = MODULE.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            return emit("BLOCKED")
        spec = importlib.util.spec_from_file_location("chat_reconciler_readonly", MODULE)
        if not spec or not spec.loader:
            return emit("BLOCKED")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        paths = sorted(mod.RECEIPTS.glob("*.json"))
        if len(paths) > MAX_RECEIPTS:
            return emit("BLOCKED")
        ids = {"Eltern": set(), "Familie": set()}
        pending = {"Eltern": 0, "Familie": 0}
        for path in paths:
            receipt, filename, route = mod.load_receipt(path)
            source = receipt.get("source", "")
            scope = source.partition("/")[0]
            if scope not in SCOPES:
                continue
            owner, grant = route
            if owner != "admin" or grant != SCOPES[scope]:
                return emit("BLOCKED")
            status = receipt.get("status")
            if status == "PREPARED":
                pending[scope] += 1
                continue
            if status not in ("SUBMITTED", "IMPORTED"):
                return emit("BLOCKED")
            # Revalidate live document digest, owner, native group ACL and
            # each active user's effective document permissions. No writes.
            pk = mod.verify(filename, receipt["sha256"], owner, grant)
            if pk is None:
                if status == "IMPORTED":
                    return emit("BLOCKED")
                pending[scope] += 1
                continue
            if type(pk) is not int or pk <= 0:
                return emit("BLOCKED")
            if status == "IMPORTED" and pk != receipt.get("document_id"):
                return emit("BLOCKED")
            ids[scope].add(pk)
            if sum(map(len, ids.values())) > MAX_MATCHES:
                return emit("BLOCKED")
        if ids["Eltern"] & ids["Familie"]:
            return emit("BLOCKED")
        emit("VERIFIED", protocol="native-chat-import-proof-v1",
             document_ids={scope: sorted(ids[scope]) for scope in SCOPES},
             pending_receipts=pending)
    except Exception:
        emit("BLOCKED")


main()
