# Paperless Bergen-AI v2: every Inbox document imported since 2026-10-01

**Status:** code and CI reviewed; production upgrade requires a separate, explicit
approved operator run on `bp-controller`. The existing parent-only v1 timer
**remains the live worker until that run completes**.

## Scope

Process all documents with the **native Paperless Inbox tag**
(`Tag.is_inbox_tag=True`) and `Document.added >=
2026-10-01 00:00:00 Europe/Berlin` (UTC instant 2026-09-30 22:00).
`added` is the immutable ingestion timestamp. **Do not use**
`Document.created` (document date), `modified`, document ID, owner
group or group-level sharing ACL as the selection boundary.

Owner may be a parent, child, non-parent, staff/admin, a technical account,
inactive user, or `NULL`; none is excluded by ownership. The existing
runtime passes `document.owner` to Paperless' native classifier, including
`None` for an unowned document. Paperless' own taxonomy resolver limits
what may be matched for that context: unowned documents may match only
unowned taxonomy objects. The v2 worker additionally never adds an Inbox
tag or another owner's private tag. No API key is required.

**Notes:** Paperless 3.3.0 permits `Note.user=NULL`. New
`Bergen-AI |` notes are saved with `user=None`, deliberately
not impersonating the document owner or an administrator. Human-facing
labels in the note are suggestions, not authority to create categories.

**Runtime prerequisites still apply:** the document retains an Inbox tag,
has at least 30 non-whitespace OCR characters, and is not part of a
version/revision chain requiring separate review. Such documents remain
unprocessed **until** they meet the criteria; the audit counts them
explicitly. This is an operational safety exception to the request for
“all documents”, not an owner/group exclusion.

**Idempotency:** the existing SQLite
`/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3`
is retained. All journal statuses are terminal to the scheduler, including
`APPLIED`, `NO_CHANGE`, `PROCESSING`, `REQUIRES_REVIEW` and
`ROLLED_BACK`; no historical replay or journal reset. The v2 worker
does NOT reset the old watermark, and it never retries an ambiguous write.
Documents previously given a human-reviewed classification but still marked
Inbox are handled with the same guarded `plan_changes` logic (titles only
if machine-imported, existing types/correspondents not overwritten, tags
only added).

## Preflight: review the Oct-1 backlog without changes

From `bp-controller`, for an operator who has the usual Vault access:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
test -z "$(git -C "$WT" status --porcelain)"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-all-inbox-oct2026-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

A successful audit reports only aggregate counts:
`ALL_INBOX_IMPORTED_FROM_CUTOFF`, `OWNERLESS_INBOX`,
`READY_FOR_CLASSIFICATION`, `WAITING_FOR_OCR_OR_UNSUPPORTED_VERSION`,
`ALREADY_JOURNALED`, `PENDING_NOT_JOURNALED`,
`EXISTING_JOURNAL_STATES`, `MODEL_INFERENCE=NO`, and
`CHANGED=False`. Neither document text nor identifiers leave the guest.

## Controlled production cutover (changes scheduler scope)

**Only after** the audit, current backup verification, review of the
privacy implications for all document owners, and separate approval for
the historical Oct-1 backfill, execute:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/upgrade-paperless-ai-inbox-catalog-all-inbox-oct2026.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{
    "paperless_ai_catalog_all_inbox_upgrade_approved": true,
    "paperless_ai_catalog_all_inbox_date_scope_approved": true,
    "paperless_ai_catalog_timer_upgrade_approved": true,
    "paperless_ai_catalog_verified_backup": true,
    "paperless_ai_catalog_notes_approved": true,
    "paperless_native_ai_ui_approved": true
  }'
)
```

This is **not** an operator command to use without having personally
reviewed and approved those terms. The command carries explicit
consent flags required by the version-pinned playbook.

The upgrade preserves the installed v1 policy and worker, stages the
new v2 files under separate protected names, pauses the same
`bergen-ai-catalog.timer` only while switching the systemd one-shot
unit, refuses if its previous job is still active, and starts the
timer afterwards. If a cutover gate fails, investigate before any
manual start. No document is modified by the upgrade playbook itself.

One eligible document per five-minute run is selected. If there is
a backlog, processing starts at lowest matching document ID among
documents whose **import timestamps** meet the cutoff. Existing
journal records are skipped; final success requires a separate
post-cutover journal audit and a visual review of at least one AI note.

## Logging and failure handling

The old systemd journal did not show the expected structured
`BERGEN_PAPERLESS_AI_CATALOG_V1:` status frames even though services
were exiting with status zero. This gap has **not** been fixed by this
upgrade. Judge productive catalogue work using the protected SQLite
journal and native notes, not only `systemctl status`.

The PostgreSQL metadata/Note transaction and separate SQLite journal
are not a distributed atomic transaction. Crash-indeterminate jobs
stay `PROCESSING` or `REQUIRES_REVIEW` and require explicit
manual reconciliation; never delete rows to force replay.
