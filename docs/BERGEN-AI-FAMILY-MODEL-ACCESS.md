# Bergen-AI: parent and child chat model access (Issues #98, #105)

Operator decision 2026-10-19: Parents AND children shall receive local chat
model access; Paperless/KI document rights are kept separate. This change
includes only a read-only preflight and no production activation.

## Role-specific model profiles

Model | Eltern | Kinder | Notes
--- | --- | --- | ---
qwen2.5:14b-instruct-q4_K_M | regular chat alias | learning-companion alias | independently scoped by group
mistral-nemo:12b | multilingual alias | child language-practice alias | independently scoped by group
bge-m3:latest | none | none | embeddings only, RAG currently off

Each of the four chat profiles must have a unique model ID with read
AccessGrants ONLY for its own exact site group. No public wildcard, no
Familie common-group model grant, no unintended workspace-write permissions.
Parents normally belong to Familie and Eltern; children to Familie and
Kinder. Shared family permissions are additive and must not disclose adult
profiles to children.

The raw provider model ID must NOT be exposed as a user-selectable model
alongside the child alias: a user selecting raw Qwen directly would bypass
the child-specific learning prompt. In Open WebUI v0.10.2, unregistered
raw models are invisible to non-admins; a separately registered custom
alias with base_model_id set to the raw Ollama ID can have its own ACL.
This is a proposed design to test, not a proven permission boundary.
System prompts are pedagogical guidance, NOT access-control enforcement.
Both child profiles MUST use the same explicit no-spoonfeeding baseline
from `feat/bergen-ai-learning-companion-20261018`:
`ansible/files/bergen_ai/prompts/learning_companion_de_v1.md`.
It forbids providing ready-to-submit homework solutions, essays, translations
or code even after requests such as "just the answer", role-play or a claimed
teacher exception. It permits stepwise hints, feedback, factual answers,
and answers to original practice exercises. This policy belongs in the
effective **system prompt** of BOTH child alias models and cannot be silently
overridden by the adult profiles. Use the versioned 10-case two-model
acceptance matrix `docs/BERGEN-AI-CHILD-NO-SPOONFEEDING-E2E.md` from the
learning-companion branch for E2E proof. This system prompt is only staged
in GitHub; it is **not installed in Open WebUI** and is no technical ACL.

## Synology OIDC and children

Issue #98 remains open. ENABLE_OAUTH_GROUP_MANAGEMENT stays false until
the IDP allowlist, absent/empty claim behavior, group departure, disabled
accounts and revocation of existing sessions are end-to-end tested.
DEFAULT_USER_ROLE remains pending for unapproved new logins. No blanket
role promotion or standing manual group management workaround.

## Read-only audit from bp-controller

Use a SEPARATE detached Git worktree:
  BASE=$HOME/bergen-platform
  WT=$HOME/bergen-platform-family-model-access
  cd "$BASE"
  git fetch origin feat/bergen-ai-family-model-access-audit-20261019
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
      ansible/playbooks/audit-bergen-ai-family-model-access-readonly.yml \
      -e "@$BASE/ansible/vars/bergen-ai-family-audit.local.yml"

The existing git-ignored local family audit YAML defines:
  bergen_ai_family_audit_host: EXISTING_BERGEN_AI_INVENTORY_HOST
  bergen_ai_family_audit_approved: true
  bergen_ai_family_group_expected:
    family: ACTUAL_COMMON_GROUP
    adults: ACTUAL_ADULT_GROUP
    children: ACTUAL_CHILD_GROUP

Do not paste this site-specific YAML, secret tokens, user IDs or raw DB rows.

Live baseline 2026-10-19 (operator-provided), confirmed:
  AUDIT=READ_ONLY
  STATUS=INVENTORY_ONLY
  FAMILY_MEMBERS=0
  ADULT_MEMBERS=0
  CHILD_MEMBERS=0
  REGISTERED_MODELS=0
  MODEL_GRANTS=0
  PUBLIC_READ_GRANTS=0
  CHILD_RAW_MODEL_READ_GRANTS=0
  CHANGED=False
  PLAY_RECAP=ok:9, changed:0, failed:0

The follow-up audit adds private aggregate counts of all Open WebUI account
roles and accounts with saved OAuth linkage. OAuth linkage proves only that
an OAuth mapping was stored, NOT the current IDP group claim or the validity
of the identity. Never infer an adult or child from an email address.
Account group provisioning requires explicit trusted identity binding,
negative tests and revocation with existing sessions.

Expected: AUDIT=READ_ONLY, CHANGED=False and aggregates of account
role/SSO linkage, group membership, registered model rows, access grants,
and direct raw model exposures.
STATUS=INVENTORY_ONLY is a narrow inventory, NOT a production clearance.
Any overlap of child/adult membership, public grant, foreign/unmatched
model grant or child direct raw model read causes REVIEW_REQUIRED.

Code reads verified existing Open WebUI SQLite through mode=ro and
PRAGMA query_only. It refuses unreviewed version, database backend,
Podman data mount, BYPASS_MODEL_ACCESS_CONTROL=true, or unexpected
three-group mapping. Outputs no user/group names or actual user IDs.

## Required follow-up

1. Verify live Open WebUI Ollama model connectivity and effective model
   registration/bypass settings (Ollama loopback presence alone is insufficient).
2. Confirm actual private SSO roster and effective user roles; design and
   test automatic group provisioning AND revocation with existing sessions.
3. Independently back up Open WebUI SQLite and demonstrate rollback.
   Stage only four private group-scoped model aliases; both child aliases
   MUST be provisioned with the no-spoonfeeding system policy from the
   learning-companion branch; bge-m3 stays hidden from interactive chat
   and embedding index stays disabled.
4. E2E test child positive chat, direct denial of parent alias and raw
   underlying model ID, denied APIs for pending or revoked users, as well
   as adults being denied child-private data. Test both UI and REST paths.
5. Retain global least-privilege baseline. Tools, websearch, coding,
   uploads, public sharing and Paperless/RAG access are separately gated.
   Never treat a child system prompt as a security mechanism.

Upstream validation reference: open-webui/open-webui tag v0.10.2,
backend/open_webui/utils/models.py,
backend/open_webui/utils/access_control/__init__.py,
backend/open_webui/models/access_grants.py.

No application user/group/model writes, Ollama downloads or service
restarts are performed by this read-only change.
