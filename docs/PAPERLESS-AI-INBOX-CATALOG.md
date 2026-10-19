# Issue #113 — Bergen Paperless-ngx v3.3.0: native AI inbox catalogue

**State:** versioned implementation in a Draft PR. No production AI config, timer,
document metadata, permissions or archives were changed by the PR. Code review,
live preflight and a one-document trial are mandatory before automatic apply.

## Target behaviour

Only **new**, OCR-complete, unreviewed inbox documents belonging to active,
non-staff users of the explicitly reviewed Paperless \`Eltern@...\` group are
eligible for the first release. The exact group is a private deployment
variable; do not hardcode domains in shared code. Children and other groups
are out of scope for the first rollout.

1. Paperless performs its ordinary import/OCR and retains its usual
   \`is_inbox_tag\` tag. Existing import routes, document owner and ACL stay intact.
2. A controlled one-shot worker calls **Paperless 3.3.0's native**
   \`get_ai_document_classification(document, document.owner, None)\` once,
   against its configured *local* Ollama backend, **with embeddings disabled**.
   This uses Paperless's native taxonomy-candidate and owner-permission logic.
3. It conditionally saves **title**, **correspondent**, **document type**, and
   **additive existing tags** (without creating categories).
   - It changes the title **only if** it still equals the original upload
     filename/stem, not after a manual title edit.
   - Correspondent/type are set only if empty; existing values are untouched.
   - Tags are only added; it refuses AI-suggested inbox tags and other
     users' private taxonomy items.
   - Original tags, especially *inbox*, remain. Date, storage path, owner,
     document permissions, original and archive files are NEVER changed.
4. It checks a full snapshot of title, owner, tags, metadata, OCR checksum,
   modified date and other fields **again after the slow LLM call under
   Django select_for_update/transaction.atomic**. Any concurrent user edit,
   changed ownership, removed inbox tag or content drift prevents the write.
5. A **separate** protected on-disk processing journal records pre- and
   post-change document state. Each document is attempted once. Failed,
   interrupted or uncertain writes remain blocked for manual review;
   automatic retries do not overwrite user corrections.
6. The operator verifies the four stored metadata fields in Paperless. Only
   the operator removes the inbox tag. The classical Paperless classifier
   can subsequently train on confirmed documents; this is NOT LLM fine-tuning.

**Limitation:** Titles already differing from the imported filename are not
automatically replaced, even if Paperless's older classifier created them.
This is intentionally safer than overwriting a possible human correction.
The review user can update such titles manually. Unrecognized taxonomy
values are not created, so a correspondent/type can remain unset.

## Approved local model routing (2026-10-19)

The operator selected the following **exact Ollama tags**, independent of
model visibility for Open WebUI users:

| Purpose | Exact Ollama model | Production use |
|---|---|---|
| Paperless inbox metadata classification | `qwen2.5:14b-instruct-q4_K_M` | Selected, awaiting one-document E2E |
| Multilingual quality comparison | `mistral-nemo:12b` | Comparison only; no automatic fallback |
| Future authorization-safe vector retrieval | `bge-m3:latest` | Explicitly **disabled** until separate RAG ACL approval |

The initial LXC-110 inventory (2026-10-19 04:06) predates the later model
installation report. **Recheck the actual Ollama model list and reachability
from Paperless LXC 126** before configuring anything. The exact
`qwen2.5:14b-instruct-q4_K_M` tag must be returned by the server which
Paperless can reach. Do not silently switch to a model from an older inventory.
Only one inference model should be loaded for the first E2E pilot to avoid
unreviewed memory pressure. Using the selected qwen2.5 text-only model does
not require embeddings and is compatible with the intended OCR-text route.

## Architecture

- Paperless 3.3.0 remains the source of truth for documents, OCR, metadata
  and rights.
- One shared local Ollama HTTP server hosts a separately configured
  Paperless model. This does **not** require Open WebUI user model access.
- We use Paperless's **native AI classifier** inside the installed Django
  application, but **not** the native "Apply AI Suggestions" workflow action,
  because its single overwrite switch cannot protect human-authored titles
  and other existing fields independently.
- The bounded five-minute systemd timer runs on **venombox** and calls
  \`pct exec 126 -- podman exec bergen-paperless\`. It is independent of
  family OIDC sync, Paperless RAG and Open WebUI.
- Metadata suggestions may consult Paperless's Tantivy similarity search
  with the actual document owner's rights. No new embedding/vector index
  is configured.
- Documents without recognized owner, with no valid inbox tag, less than
  30 characters of OCR text, versioned documents and non-parent-owned
  documents are **skipped**, left in inbox for manual review.

## Safe rollout sequence on bp-controller

Existing main inventory/vault stays in place; work in a **separate Git
worktree** to avoid the known untracked Paperless files in main:

~~~bash
(
set -euo pipefail
cd "$HOME/bergen-platform"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
test ! -e "$HOME/bergen-platform-paperless-ai-catalog"
git worktree add --detach \
  "$HOME/bergen-platform-paperless-ai-catalog" FETCH_HEAD
)
~~~

On subsequent branch updates use \`git fetch\` plus
\`git switch --detach FETCH_HEAD\`, never \`git worktree add\` again.

Copy the example into the *existing ignored local vars area* and edit it
locally without pasting site values into GitHub or chat:

~~~bash
BASE="$HOME/bergen-platform"
install -m 600 \
  "$HOME/bergen-platform-paperless-ai-catalog/docs/examples/paperless-ai-catalog.local.yml.example" \
  "$BASE/ansible/vars/paperless-ai-catalog.local.yml"
~~~

### 0a — One-command inventory with no local variables (run FIRST)

The new `audit-paperless-ai-catalog-runtime-readonly.yml` reads only
the expected LXC 126 Paperless/Django installation and loopback Ollama
`GET /api/tags` inside the expected LXC 110. It reports aggregate
inbox/OIDC counts, effective AI model status and local Ollama model
names. No document IDs, users, group names, OCR content or IP addresses
are printed. No configuration file or document is written.

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$BASE"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
if test -e "$WT/.git"; then
  cd "$WT"
  git switch --detach FETCH_HEAD
else
  test ! -e "$WT"
  git worktree add --detach "$WT" FETCH_HEAD
  cd "$WT"
fi
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-catalog-runtime-readonly.yml \
  --vault-id ai@prompt
)
~~~

**If `OLLAMA_LOOPBACK_API=UNREACHABLE`**, the model could still be hosted
elsewhere or the service may not run. Do not invent an endpoint; inspect
the private Bergen-AI service inventory in a separate audited step.
If `PARENT_GROUPS=0` or `ACTIVE_PARENT_ACCOUNTS=0`, do not bypass
the OIDC/ACL gate by treating staff accounts as regular parents.

### 1 — Read-only Paperless runtime preflight

Choose the reviewed Paperless parental group, private Ollama endpoint and
**already installed** Ollama model in the ignored vars file. Keep all
approval flags false and \`paperless_ai_catalog_mode: audit\`.

~~~bash
(
set -euo pipefail
cd "$HOME/bergen-platform-paperless-ai-catalog"
BASE="$HOME/bergen-platform"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-inbox-catalog.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
~~~

Expected: \`AUDIT=READ_ONLY\`, \`CHANGED=False\`. The status may initially be
\`AI_CONFIG_NOT_READY\`. **Do not apply** until \`STATUS=READY\`. Check
actual Paperless model availability, global AI UI **disabled**, that the Ollama endpoint
is reachable *from inside the Paperless guest*, that its DNS resolves only to
private addresses and the embedding backend is **empty**. The native
Paperless \`AIConfig\` may read effective database overrides; environment
configuration alone is not proof.

**Current runtime configuration cannot be established from GitHub.**
Do not guess Ollama's address or assume an image/model is already installed.

### 1a — Independent native Ollama settings (global AI UI stays OFF)

Paperless 3.3.0's native `get_ai_document_classification` and
`AIClient` can be used by our guarded background runner **while
`PAPERLESS_AI_ENABLED=false`**. That avoids exposing native document
chat/other AI UI features to all users, and keeps the embedding index off.

First run the **read-only** configuration audit:

~~~bash
(
set -euo pipefail
cd "$HOME/bergen-platform-paperless-ai-catalog"
BASE="$HOME/bergen-platform"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-local-ollama.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
~~~

The result contains an opaque `CURRENT_SHA256`. After independently
confirming the latest backup and Ollama's local endpoint/model, place the
**observed** hash only in the ignored local YAML file. To configure:

~~~yaml
paperless_ai_catalog_config_action: apply
paperless_ai_catalog_config_approved: true
paperless_ai_catalog_verified_backup: true
paperless_ai_catalog_config_expected_sha256: REPLACE_WITH_OBSERVED_64_HEX
~~~

Re-run the same playbook. The version-pinned ORM transaction changes
**only** `llm_backend=ollama`, the exact model and local endpoint. It
creates a protected 0600 preimage for configuration rollback; it never
enables global AI/UI/embeddings or touches document content/permissions.

Configuration rollback needs a new audit/current fingerprint,
`paperless_ai_catalog_config_action: rollback`, plus
`paperless_ai_catalog_config_rollback_approved: true`. A changed
configuration aborts instead of overwriting someone else's change.

The upstream v3.3 setting `PAPERLESS_AI_LLM_ALLOW_INTERNAL_ENDPOINTS`
defaults to true but must be effectively enabled; no unreviewed changes
to the existing Paperless environment or service restart are performed.
The worker validates private DNS and the **exact installed model** using
only Ollama's local `GET /api/tags` (no proxies or redirects).
Once `STATUS=READY` on the **worker** audit, proceed to the pilot.

### 2 — Controlled single-document pilot

Select **one** real, pre-reviewed parent-owned document that remains
in inbox and has usable OCR. Set its ID only in the ignored site-local
variables, keep \`batch_size: 1\`, set \`mode: preview\` and confirm a
positive \`ELIGIBLE_SAMPLE\`.

Before any write, independently verify your last PostgreSQL/document
backup, its restoration plan, the Paperless version and a working Ollama
connection. Explicitly set:

~~~yaml
paperless_ai_catalog_mode: apply
paperless_ai_catalog_pilot_ids: [REVIEWED_REAL_ID]
paperless_ai_catalog_approved: true
paperless_ai_catalog_verified_backup: true
~~~

Use the same Ansible command. It invokes **one** LLM classification and a
bounded, concurrency-checked metadata write. Raw IDs, OCR content, title
and LLM response remain behind \`no_log\`; the terminal prints only
summarized statuses. An unchanged inbox tag plus correct metadata must
be manually confirmed in the Paperless UI.

\`REVIEW_REQUIRED>0\`, missing metadata, a changed human title or an
LLM failure must stop further rollout. A failed or interrupted document
is not auto-retried. Inspect it privately.

### 3 — Guarded rollback of the same pilot

Only if the document is still in inbox **and has not been edited after
AI apply**, change \`mode: rollback\` in the ignored vars and explicitly
set \`paperless_ai_catalog_rollback_approved: true\`. Run the same
playbook. The runner compares the document's post-write state exactly
with its protected journal before reverting AI-added metadata and tags.
It never edits ACLs/owner/inbox. If state changed, rollback stops for
manual review instead of overwriting a human correction.

The journal lives at \`/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3\`
in Paperless's existing persisted data mount and has 0600 permissions.
Protect it with the existing data backups and NEVER copy it into Git.

### 4 — Scheduled automatic processing (a separate release gate)

**DO NOT run the timer playbook until the pilot and rollback tests pass.**

Activation installs a dedicated root-only launcher, pinned policy+worker,
protected local configuration, and a systemd timer on venombox. The timer
starts every five minutes, handles a maximum of **one** new inbox document,
does not process pre-existing history, and never clears inbox.

Set \`min_document_id\` to the **highest current Paperless document ID**
measured immediately before activation (not a guessed value), clear
\`pilot_ids\`, confirm the PostgreSQL+document backups and complete the
rollback trial, then explicitly approve:

~~~yaml
paperless_ai_catalog_mode: audit
paperless_ai_catalog_pilot_ids: []
paperless_ai_catalog_min_document_id: REPLACE_WITH_CURRENT_HIGH_WATER_MARK
paperless_ai_catalog_timer_activate: true
paperless_ai_catalog_timer_approved: true
paperless_ai_catalog_pilot_passed: true
paperless_ai_catalog_approved: true
paperless_ai_catalog_verified_backup: true
~~~

Execute \`ansible/playbooks/deploy-paperless-ai-inbox-catalog-timer.yml\`
with the same inventory, Vault ID and ignored vars file. Verify:
\`systemctl is-enabled bergen-ai-catalog.timer\`,
\`systemctl list-timers bergen-ai-catalog.timer\`,
\`journalctl -u bergen-ai-catalog.service\` (only bounded statuses).
Rollback automation activation immediately by disabling this timer; do
not clear or repurpose the processing journal without separate review.

The code enforces the watermark, dedicated adult scope and per-document
journal. **Any unexpected permission, title, OCR, tag or owner change
during classification halts that document for manual review.**

## Known limitations / remaining acceptance gates

- No live execution has happened from this GitHub PR; bp-controller and the
  productive Proxmox shell are NOT accessible from the GitHub connector.
- The initial rollout intentionally excludes child/private child-owned
  documents and pre-watermark historical documents. Add them only through a
  separately audited owner-/group-specific release.
- Manual title changes *before* the worker first inspects a document are
  detected via conservative original-filename equality, not a complete
  user-edit provenance record; ambiguous titles are never overwritten.
- Rollback is only automatic while the document is still in inbox and has
  no modifications after the recorded post-AI state.
- Metadata suggestion reliability and speed must be measured for the
  actual installed model; empty OCR, model timeout/JSON errors, new tag
  proposals and manually pre-edited fields are required regression tests.
- The native local Ollama client requires a separately approved,
  rollbackable ORM setting change; **global Paperless AI/UI stays OFF**,
  embeddings remain disabled, and no service restart is performed.
  No users/groups, document permissions or RAG/document chat are activated. Family group sync (#98) and parent-only live AI→Paperless
  retrieval (#63) remain separate controlled releases.

## Upstream source pinned and reviewed

- \`paperless-ngx/paperless-ngx@v3.3.0\`:
  \`src/documents/workflows/ai.py\`,
  \`src/paperless_ai/ai_classifier.py\`,
  \`src/paperless_ai/matching.py\`,
  \`src/paperless/config.py\`.
- Native suggestions skip blank OCR. The native action has one global
  \`ai_overwrite_existing\` toggle; this implementation does **not** use it
  for unsafe shared-field overwrites.
- Documentation: https://docs.paperless-ngx.com/advanced_usage/ and
  https://docs.paperless-ngx.com/configuration/.
