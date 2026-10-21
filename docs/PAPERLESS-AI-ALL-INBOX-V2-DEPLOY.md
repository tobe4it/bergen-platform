# Bergen-AI v2 rollout: all Inbox documents imported since 2026-10-01

## Exact approved processing scope

- **Tag:** Native Paperless Inbox tag (`Tag.is_inbox_tag=True`).
  Do not match a tag merely by its displayed name.
- **Date:** `Document.added >= 2026-10-01 00:00:00 Europe/Berlin`
  (timestamp timezone offset was UTC+02:00 on that date);
  **not** `Document.created`, not document ID or the old timer watermark.
- **Owners:** No owner/group/staff predicate. Includes personal, group-shared,
  technical-account, administrator-owned and ownerless documents. There is no
  implicit ACL grant to the original document owner.
- **Existing protections:** at least 30 OCR characters; no linked document
  revisions; document must still carry Inbox tag before commit; do not remove
  Inbox tag, change ACL/owner or overwrite user-entered metadata; no new
  type/tag objects; no reprocessing of **any** journaled ID (success,
  `NO_CHANGE`, review, processing or rollback).
- **Native classifier:** Paperless ML runs independently on import; Bergen-AI
  uses local Ollama Qwen only afterward. For owned documents, suggestion
  resolution uses their existing Paperless owner ACL. For ownerless documents,
  the classifier's `user=None` path and native matching routines restrict
  *taxonomy matches* to unowned/global objects. Ownerless documents do not
  acquire an artificial owner.
- **Notes:** In catalog v2 the note is recorded with native `Note.user=None`
  (system-produced), not impersonating a human owner. Paperless 3.3
  permits this nullable field. Notes do not change document permissions.
- **Errors:** strict per-document status journal, no automatic retries,
  human review for write-indeterminate conditions. PostgreSQL and SQLite
  are separate transaction domains; status `REQUIRES_REVIEW` is
  required for crash recovery.

**Important:** `start_added_date` is fixed to `2026-10-01` in v2. Older
catalog v1 is retained for audit/compatibility, but the new scope cannot be
enabled merely by changing variables in the old v1 timer deploy.

## Deployment status

The GitHub feature branch carries reviewed Python worker/policy v2,
a separate **operator-approved** upgrade playbook, and offline regression
tests. Nothing in this commit changes the live timer. Use the commands
below from the existing `bp-controller` worktree. Do not paste
Markdown headings or commentary into the shell.

### 1. Sync and verify (no writes to production)

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"

test -z "$(git -C "$WT" status --porcelain)" || {
  echo "STOP: local uncommitted work"; exit 1;
}
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/upgrade-paperless-ai-all-inbox-since-20261001.yml \
  --syntax-check
)
```

### 2. Explicit production upgrade (timer pauses during file installation)

The operator's existing October 2026 CT126 NFS backup was accepted
for this project. `verified_backup=true` must still mean an
actual reviewed backup, not just a file exists. Check there is no
active manual AI classification task or other deployment in flight.

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/upgrade-paperless-ai-all-inbox-since-20261001.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{
    "paperless_ai_catalog_v2_upgrade_approved": true,
    "paperless_ai_catalog_v2_all_owners_approved": true,
    "paperless_ai_catalog_v2_history_from_october_approved": true,
    "paperless_ai_catalog_verified_backup": true
  }'
)
```

The playbook checks the original v1 policy, live active timer,
Paperless guest identity, current Qwen backend and model, and a
read-only v2 scope preview **before any production file write**.
It disables the existing timer, rejects active inference,
backs up and installs only the worker/policy and root-owned JSON
runtime settings, verifies the installed v2 policy, then
reenables the original timer. It does not modify the native
Paperless ML/UI, permissions, files or network. If anything
fails during deployment, the timer stays **disabled** pending
review; it does not automatically revert or replay document
operations.

Success summary:

```text
TIMER=ENABLED
SELECTION=ALL_DOCUMENTS_WITH_INBOX_TAG
ADDED_FROM=2026-10-01T00:00:00_EUROPE_BERLIN
OWNER_FILTER=NONE
ID_WATERMARK=NOT_USED
NOTES=SYSTEM_ATTRIBUTED
EXISTING_JOURNAL_RECORDS=SKIPPED_NO_RETRY
DOCUMENT_INBOX_TAG=RETAINED
BATCH_SIZE=1
```

Verify subsequent status read-only with:

```bash
"$HOME/bergen-platform/.venv/bin/ansible" venombox \
  -i "$HOME/bergen-platform-paperless-ai-catalog/ansible/inventory.yml" \
  -i "$HOME/bergen-platform/ansible/inventory.local.yml" \
  --vault-id ai@prompt -b -m ansible.builtin.command \
  -a "systemctl show bergen-ai-catalog.timer -p ActiveState -p UnitFileState"
```

**Caution:** The existing `audit-paperless-ai-timer-journal-readonly.yml`
is scoped to v1 parent/ID-watermark policy; it must not be used as
a v2 scope audit. A separate v2 audit is needed for aggregate
date-based processing verification.

Workloads with an exceptionally large historic backlog may hit the
current 2,000-document scan cap before the oldest 2,000 records have
been journalized; do not interpret an empty run in that case as all
eligible documents processed. Address scanning/pagination before
scaling to large archives.
