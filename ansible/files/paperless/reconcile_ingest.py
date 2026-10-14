#!/usr/bin/env python3
"""Verify imported Paperless documents before acknowledging staging receipts.

Safe by default: without --commit only displays what would be acknowledged.
Neither mode deletes source files, consumes files, or Paperless documents.
"""
import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path

ROOT = Path("/srv/bergen-paperless/ingest-bridge-state")
RECEIPTS = ROOT / "receipts"
ROUTES = {
    "Privat/thomas": ("thomas", ""),
    "Privat/nadja": ("nadja", ""),
    "Eltern": ("admin", "Eltern@bergen.intern"),
    "Familie": ("admin", "Familie@bergen.intern"),
}

DJANGO_VERIFY = """
import os
from documents.models import Document
from guardian.shortcuts import get_groups_with_perms, get_users_with_perms
from documents.permissions import permitted_document_ids
from django.contrib.auth.models import Group, User

PARENTS = ('nadja', 'thomas')
name = os.environ['BP_FILENAME']
expected_owner = os.environ['BP_OWNER']
checksum = os.environ['BP_SHA256']
scope = os.environ['BP_GROUP']
docs = list(Document.objects.filter(original_filename=name))
if not docs:
    print('BP_IMPORT:PENDING')
else:
    assert len(docs) == 1, 'multiple documents with this filename'
    doc = docs[0]
    assert doc.root_document_id is None, 'unexpected version'
    assert doc.checksum == checksum, 'checksum differs'
    assert doc.owner is not None and doc.owner.username == expected_owner, 'wrong owner'
    assert doc.page_count is not None and doc.page_count > 0, 'no valid pages'

    group = Group.objects.get(name=scope) if scope else None
    actual_groups = {
        group_obj.name: set(perms)
        for group_obj, perms in get_groups_with_perms(doc, attach_perms=True).items()
    }
    if scope == 'Eltern@bergen.intern':
        expected_groups = {scope: {'view_document', 'change_document'}}
    elif scope == 'Familie@bergen.intern':
        expected_groups = {scope: {'view_document'}}
    else:
        expected_groups = {}
    assert actual_groups == expected_groups, 'group permissions differ'

    direct_grants = get_users_with_perms(doc, attach_perms=True)
    for grantee, permissions in direct_grants.items():
        assert group is not None, 'unexpected private-document direct grant'
        assert grantee.groups.filter(pk=group.pk).exists(), 'direct grant to outsider'
        actual = set(permissions)
        if scope == 'Familie@bergen.intern' and grantee.username in PARENTS:
            assert actual == {'view_document', 'change_document'}, 'parent family rights differ'
        elif scope == 'Eltern@bergen.intern' and grantee.username in PARENTS:
            # Paperless may redundantly emit a direct change grant when the
            # change_group assignment runs. Both sets are explicitly scoped.
            assert actual in ({'view_document'},
                              {'view_document', 'change_document'}), 'parent rights differ'
        else:
            assert actual == {'view_document'}, 'unexpected direct permission'

    if scope == 'Familie@bergen.intern':
        for name in PARENTS:
            parent = User.objects.get(username=name)
            assert parent in direct_grants, 'missing family parent grant: ' + name
            assert set(direct_grants[parent]) == {
                'view_document', 'change_document'
            }, 'incomplete family parent rights: ' + name

    # Check every ACTIVE user, not only the accounts imported today. This
    # protects private boundaries and verifies no delete access to shared
    # documents. The admin owner is the sole delete-capable shared principal.
    for user in User.objects.filter(is_active=True).iterator():
        member = group is not None and user.groups.filter(pk=group.pk).exists()
        expected_view = user.is_superuser or user.pk == doc.owner_id or member
        expected_change = (
            user.is_superuser or user.pk == doc.owner_id or
            (scope == 'Eltern@bergen.intern' and member) or
            (scope == 'Familie@bergen.intern' and user.username in PARENTS)
        )
        expected_delete = user.is_superuser or user.pk == doc.owner_id
        for perm, expected in (
            ('view_document', expected_view),
            ('change_document', expected_change),
            ('delete_document', expected_delete),
        ):
            effective = permitted_document_ids(user, perm=perm).filter(pk=doc.pk).exists()
            assert effective == expected, (
                'effective permission differs for ' + user.username + ':' + perm
            )
            if expected:
                assert user.has_perm('documents.' + perm), (
                    'missing global model right for ' + user.username + ':' + perm
                )
    print('BP_IMPORT:VERIFIED:' + str(doc.pk))
"""


def secure_dir(path):
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or stat.S_IMODE(s.st_mode) != 0o700:
        raise RuntimeError("unsafe journal directory: " + str(path))


def load_receipt(path):
    if not re.fullmatch(r"[0-9a-f]{24}\.json", path.name):
        raise RuntimeError("unexpected journal filename")
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_nlink != 1 or stat.S_IMODE(s.st_mode) != 0o600 or s.st_size > 16384:
        raise RuntimeError("unsafe journal file")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("invalid journal format")
    source = receipt.get("source")
    destination = receipt.get("destination")
    digest = receipt.get("sha256")
    if not all(isinstance(v, str) for v in (source, destination, digest)):
        raise RuntimeError("missing journal fields")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("invalid SHA256")
    source_parts = source.split("/")
    if len(source_parts) not in (2, 3) or any(p in ("", ".", "..") for p in source_parts):
        raise RuntimeError("invalid source path")
    scope = "/".join(source_parts[:-1])
    if scope not in ROUTES or not source_parts[-1].lower().endswith(".pdf"):
        raise RuntimeError("disallowed source scope")
    name = Path(source_parts[-1]).stem[:150] + "--bp-" + path.stem + ".pdf"
    if destination != scope + "/" + name:
        raise RuntimeError("invalid destination")
    if receipt.get("status") not in ("PREPARED", "SUBMITTED", "IMPORTED"):
        raise RuntimeError("unexpected receipt status")
    return receipt, name, ROUTES[scope]


def verify(filename, checksum, owner, group):
    env = os.environ.copy()
    env.update(BP_FILENAME=filename, BP_SHA256=checksum,
               BP_OWNER=owner, BP_GROUP=group)
    args = ["podman", "exec", "-e", "BP_FILENAME", "-e", "BP_SHA256",
            "-e", "BP_OWNER", "-e", "BP_GROUP",
            "bergen-paperless", "python", "/usr/src/paperless/src/manage.py",
            "shell", "-c", DJANGO_VERIFY]
    process = subprocess.run(args, env=env, text=True,
                             capture_output=True, timeout=90, check=False)
    if process.returncode:
        raise RuntimeError("Paperless verification failed: " + process.stderr[-500:] + process.stdout[-500:])
    lines = [x for x in process.stdout.splitlines() if x.startswith("BP_IMPORT:")]
    if lines == ["BP_IMPORT:PENDING"]:
        return None
    if len(lines) != 1 or not re.fullmatch(r"BP_IMPORT:VERIFIED:[0-9]+", lines[0]):
        raise RuntimeError("unexpected Paperless response")
    return int(lines[0].rsplit(":", 1)[-1])


def persist(path, receipt):
    # Atomic replace and directory sync: no partial acknowledged state.
    with tempfile.NamedTemporaryFile(mode="w", dir=RECEIPTS,
                                     prefix=".ack-", encoding="utf-8",
                                     delete=False) as stream:
        tmp = Path(stream.name)
        try:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
        d = os.open(RECEIPTS, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        tmp.unlink(missing_ok=True)


def main(commit):
    if os.geteuid() != 0:
        raise RuntimeError("root required")
    os.umask(0o077)
    secure_dir(ROOT)
    secure_dir(RECEIPTS)
    with (ROOT / "bridge.lock").open("a+") as lock:
        flock(lock, LOCK_EX | LOCK_NB)
        failures = []
        for path in sorted(RECEIPTS.iterdir()):
            if path.name.startswith("."):
                continue
            try:
                receipt, name, (owner, group) = load_receipt(path)
                if receipt["status"] == "IMPORTED":
                    print("ALREADY_IMPORTED", path.name, receipt.get("document_id"))
                    continue
                if receipt["status"] == "PREPARED":
                    print("MANUAL_REVIEW", path.name, "PREPARED")
                    continue
                document_id = verify(name, receipt["sha256"], owner, group)
                if document_id is None:
                    print("PENDING", path.name)
                elif not commit:
                    print("VERIFIED", path.name, "document", document_id, "(dry-run)")
                else:
                    receipt["status"] = "IMPORTED"
                    receipt["document_id"] = document_id
                    receipt["imported_at"] = time.time()
                    persist(path, receipt)
                    print("IMPORTED", path.name, "document", document_id)
            except Exception as exc:
                print("REJECTED", path.name, str(exc), flush=True)
                failures.append(path.name)
        if failures:
            raise RuntimeError("reconciliation failed: " + ", ".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    main(parser.parse_args().commit)
