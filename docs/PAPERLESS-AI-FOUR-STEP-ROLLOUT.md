# Paperless 3.3 Bergen 4-step pipeline – guarded rollout

**Desired order (operator confirmed 2026-10-20):**

1. Paperless imports and OCRs the document.
2. Paperless's classic, non-LLM classification/matching runs.
3. Bergen-AI (BAI) classifies only eligible **new** parent-owned Inbox
   documents asynchronously via local Ollama Qwen. On a normal AI/matching/
   validation/note write failure, the Paperless metadata/notes transaction
   rolls back and a sanitized error stage/code is journalled to the existing
   private 0600 SQLite catalogue. The entry is never automatically retried.
   Valid but non-applicable suggestions are `NO_CHANGE`, not errors.
   On successful processing, existing permitted metadata may be applied
   and an owner-attributed Paperless Note records bounded tag/type
   suggestions. No new taxonomy entries are created, Inbox remains.
4. An operator may **optionally** use Paperless's *native* AI suggestions
   from the document view and manually accept or reject them.

## Activation status and caveats

The following features are **implemented in this branch but not yet enabled
on the live Paperless instance** by any GitHub commit alone:

- Error-stage/code recording for *future* failures. Existing failed IDs
  11, 16, 21, 22 contain no recoverable old cause and stay blocked.
- An atomic per-document PostgreSQL metadata/Note transaction plus the
  existing durable, locked, per-ID SQLite journal.
- Valid `NO_CHANGE` terminal journal status and idempotent no-retry handling.
- Owner-attributed native document Notes, requiring `documents.add_note`
  (and view permission) for the exact active parent group.
- Native Paperless `ai_enabled` switch, independently configured through
  the singleton and protected with a live state fingerprint.
- Timer prerequisites verifying the live local-only Ollama config, UI master
  ON, embeddings OFF, parent model-level Note rights and exact new-document
  watermark. The timer is a separate explicit deployment.

**Important cross-database limit:** Paperless's document metadata/notes
live in PostgreSQL whereas Bergen's processing journal lives in SQLite.
The two commits cannot be made globally atomic without an architectural
migration. In a rare crash or journal write failure after PostgreSQL
commit, a document may have changed even if the journal update failed.
The locked `REQUIRES_REVIEW` state and optimistic snapshot audit must
detect/reconcile this; do **not** claim that *every imaginable* failure
means zero document changes. No blind retry or automatic rollback.

The AI master switch is **global** in Paperless, not just for parents.
Document access remains guarded by Paperless permissions; it also exposes
the *native* AI suggestion controls to other authorized users. The
embedding backend and cross-document RAG/chat index remain OFF. Before
wider rollout, review whether the interface is suitable for child accounts.

Paperless auto-fetches suggestions for Inbox documents on opening by
default. To make step 4 *strictly optional*, each account must turn off
**Settings → Documents → Automatically request suggestions for inbox
documents**. Leave the suggestion button available for manual use.
Set suggestion source to **AI** or **Both** when required.

### Stage A – sync worktree, read-only audits

From `bp-controller`, using the existing non-versioned private variables:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
test -z "$(git -C "$WT" status --porcelain)"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"

for PLAY in manage-paperless-ai-native-notes.yml \
            manage-paperless-native-ai-suggestions-ui.yml; do
  "$BASE/.venv/bin/ansible-playbook" \
    -i ansible/inventory.yml \
    -i "$BASE/ansible/inventory.local.yml" \
    "ansible/playbooks/$PLAY" \
    --vault-id ai@prompt \
    -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
done
)
```

The second audit emits an opaque `CURRENT_SHA256` tied to the current
exact native AI configuration. Do not reuse any historical fingerprint.

### Stage B – narrow Note permissions (one controlled apply)

Only after reviewing Stage A, and relying on the operator's expressly
accepted 19 October 2026 structurally validated CT126 backup:

```bash
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-native-notes.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{"paperless_ai_notes_permission_mode":"apply",
       "paperless_ai_notes_permission_approved":true,
       "paperless_ai_catalog_verified_backup":true}'
```

This may grant **only** add/view Note model permissions to the
existing `Eltern@bergen.intern` group; it creates no notes.

### Stage C – native AI suggestion UI (one controlled apply)

Use `CURRENT_SHA256` from **the Stage A UI audit on the same current
configuration**; replace `REPLACE_WITH_AUDIT_SHA256` below:

```bash
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-native-ai-suggestions-ui.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{"paperless_native_ai_ui_mode":"apply",
       "paperless_native_ai_ui_approved":true,
       "paperless_ai_catalog_verified_backup":true,
       "paperless_native_ai_ui_expected_sha256":"REPLACE_WITH_AUDIT_SHA256"}'
```

If the active Paperless front-end does not show Suggest after a
successful guarded audit, check live application configuration
and front-end session state. Do not restart production services
without separate review.

### Stage D – validate the NEW worker with one document; timer still OFF

The *previous* 3/8 successful samples used the old worker and
cannot prove this revised Note/NO_CHANGE implementation.
The sole formerly not-recorded, already operator-approved
candidate 29 can be used for a newly approved, bounded trial
only after a fresh eligible selection audit and explicit
confirmation of safe Note permissions.

```bash
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-inbox-catalog.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{"paperless_ai_catalog_pilot_ids":[29],
       "paperless_ai_catalog_batch_size":1,
       "paperless_ai_catalog_mode":"preview"}'
```

Demand exactly one eligible document, no model inference, no writes.
Only then repeat with:
`paperless_ai_catalog_mode="apply"`,
`paperless_ai_catalog_approved=true`,
`paperless_ai_catalog_verified_backup=true`,
`paperless_ai_catalog_notes_enabled=true`,
`paperless_ai_catalog_notes_approved=true`.
Demand `APPLIED=1` or `NO_CHANGE=1`, `NOTES_ADDED=1`,
`REVIEW_REQUIRED=0`, inspect real doc metadata + exactly one new
attributed Note before advancing. No classification of documents
11, 16, 21, 22 without a separate journal-recovery approval.

### Stage E – activate *only for subsequently imported documents*

After successful Stage D and a current read-only inventory:

- For first activation, select the explicit one-time override
  `paperless_ai_catalog_initial_use_current_max_id=true`.
  The deployment captures the current maximum existing document ID
  *on venombox* and persists that exact watermark. It refuses this
  automatic selection if the timer is already enabled. Alternatively,
  preselect an exact positive ID in the private configuration and
  the playbook will require it equal the live maximum.
- Set `paperless_ai_catalog_pilot_ids` to an empty list only for the
  scheduled rollout; never leave a reviewed pilot ID in a timer config.
- Run `deploy-paperless-ai-inbox-catalog-timer.yml` with per-invocation,
  explicit `paperless_ai_catalog_timer_activate=true`,
  `paperless_ai_catalog_timer_approved=true`,
  `paperless_ai_catalog_pilot_passed=true`,
  `paperless_ai_catalog_approved=true`,
  `paperless_ai_catalog_verified_backup=true`,
  `paperless_ai_catalog_notes_enabled=true`,
  `paperless_ai_catalog_notes_approved=true`,
  `paperless_native_ai_ui_approved=true`, and for first activation
  `paperless_ai_catalog_initial_use_current_max_id=true`.
- The schedule is every five minutes, one newly eligible
  document per invocation. Unprocessed old docs and all
  recorded review cases are excluded. No timer activation
  if any readiness check fails.

**Separate operational issues:** CT126's scheduled backup failed on
20 October with exit code 255 despite the accepted 19 October
archive; this recurring backup reliability must be resolved for
long-term production operation. Ollama still exposes unauthenticated
TCP/11434 beyond the intended Paperless guest; no bridge/firewall
changes were authorized by this feature.

## Live read-only preview of document 29 – 2026-10-20 19:23

The operator executed `manage-paperless-ai-inbox-catalog.yml` in
`mode=preview` against explicitly selected document 29 on the
live 3.3.0 Paperless service, after granting the two parent Note
model permissions and enabling the native Paperless AI UI.

```text
AUDIT=READ_ONLY
STATUS=READY
PAPERLESS_VERSION=3.3.0
ELIGIBLE_SAMPLE=1
APPLIED=0
NO_CHANGE=0
NOTES_ADDED=0
ERROR_STAGE=NONE
ERROR_CODE=NONE
REVIEW_REQUIRED=0
ALREADY_RECORDED=0
ROLLED_BACK=0
CHANGED=False
venombox ok=9 changed=0 failed=0 skipped=2
```

**Decision gate:** This proves current eligibility and configuration,
**not** that the new Note writer, local Ollama model inference, or
post-inference transaction is runtime-validated. The successful
`preview` does not check persistent journal occupancy; read-only
inventory last showed document 29 `NOT_RECORDED`, but it should be
checked again immediately before the one-document `apply` if there
may have been other operator activity. Do not start the automatic timer
solely on this preview.

The next reviewed trial may invoke exactly `pilot_ids=[29]`,
`batch_size=1`, `mode=apply`, `approved=true`,
`verified_backup=true`, `notes_enabled=true` and
`notes_approved=true`. A successful, verified outcome is either
`APPLIED=1` or `NO_CHANGE=1`, plus `NOTES_ADDED=1`,
`REVIEW_REQUIRED=0`, `ALREADY_RECORDED=0`. Inspect the
real Note and remaining Inbox tag in the Paperless UI before
timer rollout. An unexpected result is a stop, never a retry.
