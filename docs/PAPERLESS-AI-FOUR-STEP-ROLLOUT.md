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

## Live timer deployment observed 2026-10-20 19:25 – pilot verification missing

Operator provided the complete final section of a successful
`deploy-paperless-ai-inbox-catalog-timer.yml` execution. Live output:

```text
WATERMARK_MUST_EQUAL_LIVE_MAX_DOCUMENT_ID assertion: PASSED
Native AI / parent Note rights readiness: PASSED
Existing timer upgrade gate: PASSED
Timer files, policy, launcher and service installed
TIMER=ENABLED
SCOPE=ONLY_NEW_POST_WATERMARK_ELTERN_INBOX_DOCUMENTS
NOTES=ENABLED_FOR_VALIDATED_CLASSIFICATION_ONLY
FAILURE=PRIVATE_JOURNAL_ONLY_NO_RETRY
INBOX_TAG_REMOVAL=NEVER
DOCUMENT_PERMISSIONS=UNCHANGED
venombox ok=23 changed=6 failed=0 unreachable=0
```

**Operational discrepancy:** The last observable operation on
Document 29 was a `mode=preview` run at 19:23 with
`STATUS=READY`, `ELIGIBLE_SAMPLE=1`, and `CHANGED=False`.
There is **no provided result** showing the required modified-worker
`mode=apply` proof with `NOTES_ADDED=1`. The timer gate trusted
caller-supplied `paperless_ai_catalog_pilot_passed=true`, not a
cryptographically verified live evidence record. Timer activation
thus succeeded even though its pilot proof is not demonstrated in
this conversation; don't claim pilot or end-to-end note writes
validated. Nor has anyone yet shown the timer service actually ran
and classified an imported document.

**Recommended controlled remediation:** Stop the timer schedule
temporarily without deleting deployed files, modifying the journal,
or killing an in-flight oneshot:

```bash
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible" venombox \\
  -i ansible/inventory.yml \\
  -i "$BASE/ansible/inventory.local.yml" \\
  --vault-id ai@prompt -b -m ansible.builtin.command \\
  -a "systemctl stop bergen-ai-catalog.timer"
```

This is an operator-run, explicit reversible timer stop, not a
modification performed by the GitHub PR. It does not in itself prove
that an in-progress `bergen-ai-catalog.service` is absent. Confirm
service and timer status with read-only `systemctl is-active` checks
and review bounded, sanitized `journalctl` output (do not disclose
OCR or full prompts). Determine whether any new documents were processed
since activation. Verify the one-document changed-worker path and
snapshot/note invariants before any restart of automation. The
already accepted 19 October backup is not evidence of a successful
post-change restore or a recently functioning 20 October backup.


## Post-activation journal observability – read-only verification

The operator observed many successful
`bergen-ai-catalog.service` oneshot executions with 0 exit status
at and after 2026-10-20 21:56 CEST. A query for the structured
`BERGEN_PAPERLESS_AI_CATALOG_V1:` records in
`journalctl -u bergen-ai-catalog.service` returned **zero matches**.
The grep command's `|| true` suppresses a nonzero status for
no matches. Therefore there is no positive evidence yet that a
new document was classified or that a Note was written.

The unit declares `StandardOutput=journal`, and the Django
worker prints one sanitized frame per normal invocation. The
missing frames remain an **unresolved logging/transport issue**,
not proof of LLM failure or of a healthy catalogue. The short
service execution is consistent with an empty post-watermark
candidate set, but the watermark/document inventory must verify
this independently.

To avoid a new inference, manual replay, or any write to
Paperless, run the additional version-pinned **read-only**
`audit-paperless-ai-timer-journal-readonly.yml` from the pinned
feature branch. It reads the root-only installed service policy
(never displays its endpoint or actual watermark), then uses
the Paperless ORM to count newly created documents, parent-owned
Inbox documents and those with OCR, plus a read-only SQLite
query for post-watermark journal states. It also counts native
BAI notes only as an aggregate and never discloses note contents,
document IDs or private owner mappings.

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
  ansible/playbooks/audit-paperless-ai-timer-journal-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

Interpretation:

- `NEW_DOCUMENTS=0` and `POST_WATERMARK_JOURNAL_TOTAL=0`:
  no documents were created since activation, so no work was expected.
- Positive `NEW_PARENT_INBOX_WITH_OCR` with zero journal entries:
  new candidate documents exist, but the reason for no worker
  processing remains to be investigated (additional eligibility
  rules may apply).
- `APPLIED` or `NO_CHANGE` positive: a BAI worker attempt
  reached a journal-confirmed success state; `NEW_PARENT_AI_NOTES`
  independently shows attributable stored native notes.
- `REQUIRES_REVIEW` or `PROCESSING` positive:
  investigate error stage and protected entry in a separate
  bounded, explicit read-only audit; **never auto-retry**.
- All zeros do not by themselves establish missing logs as
  a defect; improve observability separately.

Do not disable, redeploy or trigger the timer merely
because the systemd logs have no framed records.
