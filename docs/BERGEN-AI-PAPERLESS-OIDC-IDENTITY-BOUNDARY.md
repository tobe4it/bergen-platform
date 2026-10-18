# Bergen-AI ↔ Paperless: OIDC identity boundary preflight

Tracking: [Issue #98](https://github.com/tobe4it/bergen-platform/issues/98)
and [PR #63](https://github.com/tobe4it/bergen-platform/pull/63).
Follow-up to the confirmed [36-case Paperless DRF audit](PAPERLESS-DRF-EFFECTIVE-AUDIT.md).

## Objective

Bergen-AI must ask Paperless **on behalf of the actual authenticated user**.
Neither an AI group named `Familie` nor a shared Paperless service account
establishes the right to retrieve or summarize arbitrary Paperless documents.

This PR does not enable Paperless retrieval. Its only objective is to find out
whether the existing OIDC identities in Open WebUI and Paperless can even be
correlated without relying on names or email addresses alone.

## Three independent rights decisions

1. Synology SSO establishes `(issuer, subject)` and signed groups for the
   authenticated user. A site's actual group names/UUIDs/DNs are environment
   specific; the semantic roles `family/adults/children` are not claim values.
2. Bergen-AI uses **verified** group data only for AI-function authorization
   and for its *own* private models/knowledge. Open WebUI 0.10.2 has unsafe
   empty/absent-claim revocation semantics; its native group synchronization
   remains disabled until explicitly replaced or secured.
3. Paperless decides readable document IDs using **effective object ACLs**
   (`permitted_document_ids(..., perm='view_document')` or equivalent real
   user-authenticated Paperless API), including owner, direct-user and group
   grants. This cannot be inferred solely from groups or tags.

A future AI retrieval broker must accept only a **server-authenticated
session identity** and validate a matching Paperless user before searching.
It must authorize *every* search result/chunk, preview/download/citation,
and cached text before any LLM context is assembled. On unavailable or
ambiguous identity, Paperless API failure or revoked/changed ACLs, it
must **fail closed**. A globally privileged Paperless API token in an
Open WebUI tool, unfiltered shared RAG index or cached pre-authorization
document text is not acceptable.

## Read-only cross-service identity audit (this PR)

The operator runs `ansible/playbooks/audit-bergen-ai-paperless-oidc-identity-readonly.yml`
from the existing Ansible controller. It uses the installed version of
Open WebUI **0.10.2**, the running Bergen-AI `open-webui` container and
the established unprivileged Paperless LXC **126** with its existing
`bergen-paperless` container.

- A one-use 64-character random HMAC challenge is generated on the
  controller using Ansible's `password` lookup with `/dev/null`.
  It is transmitted to the two inspection processes **only over stdin**.
- Bergen-AI reads `user.email` and `user.oauth[provider].sub`
  through SQLite `mode=ro` and `PRAGMA query_only=ON`; it never reads
  passwords, tokens or message contents.
- Paperless reads Django-allauth `SocialAccount.uid` and, when present,
  `extra_data.sub`, plus the linked account's active state and email
  **in process**, without fetching documents or altering database rows.
- Both processes return **HMAC fingerprints**, not identifiers. Their
  results and the challenge are held in `no_log` Ansible variables;
  the controller compares the fingerprints in memory.
- Only aggregate counts/classifications are printed. An equal email
  alone **never** counts as a match; both a stable subject candidate and
  the same email must match and the Paperless user must be active.
- No persistent HMAC database or identity roster is created. A run's
  HMACs are not useful for correlating future runs because the key changes.
  If a site stores OIDC provider-specific subject encodings, the
  result may be `REQUIRES_IDENTITY_REVIEW`; that is not permission to
  rewrite accounts or relax the check.

Default Open WebUI provider label `oidc` and Paperless allauth provider
label `openid_connect` **are only initial inspection selectors**. If the
installed site's labels differ, pass the actual selector using a private
ignored Ansible variables file after read-only verification; do not match
every provider. Neither selector is a hardcoded domain/group namespace.

**Crucial limitation:** This is *not* proof that both apps use the same
OIDC issuer: Open WebUI 0.10.2 retains `sub` but does not persist
the issuer alongside `user.oauth`. The audit therefore prints
`ISSUER_EQUALITY=NOT_PROVEN`, plus `LIVE_USER_DELEGATION=NOT_PROVEN`,
`PAPERLESS_DOCUMENT_ACL=NOT_PROVEN`,
`GROUP_CLAIM_VALIDITY=NOT_PROVEN` and
`AUTOMATIC_GROUP_SYNC_SAFE=NO` **even when subjects match**.

## Command – bp-controller, separate worktree

Never paste a bearer token, raw ID token, Subject, email or full document
ACL into a chat or repository. This audit requires **no bearer token**.

```bash
(
set -euo pipefail

cd "$HOME/bergen-platform-ai-family-audit"
git fetch origin feat/bergen-ai-paperless-identity-boundary-20261018
test ! -e "$HOME/bergen-platform-ai-paperless-identity"
git worktree add --detach \
  "$HOME/bergen-platform-ai-paperless-identity" FETCH_HEAD
cd "$HOME/bergen-platform-ai-paperless-identity"

BASE="$HOME/bergen-platform"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-paperless-oidc-identity-readonly.yml \
  -e oidc_identity_audit_approved=true
)
```

No Vault password is needed because no API or OIDC credentials are
used. Operator privileges for the existing Paperless LXC are required.
Expected Ansible result: `changed=0`. A `LINK_CANDIDATES_PRESENT`
result is a *candidate for further user-bound authorization testing*,
not acceptance. If no candidates match, do **not** use email-only
delegation as a shortcut.

## Next protected development steps

1. Confirm and pin real OIDC provider identifiers, issuer and legitimate
   subject semantics from both apps with a user-controlled non-sensitive
   trace. Investigate any account-state mismatch.
2. Independently examine effective Paperless Django Guardian object ACLs
   for already approved group/private/child/parent test identities.
   The existing 36/36 test covers selected documents only.
3. Design a **server-side** per-request identity-bound Paperless access
   broker. A service transport identity may be privileged only if
   the broker enforces Paperless's real-user effective ACL *before*
   every document content/embedding/summary is exposed.
4. Negative E2E tests for child querying parent-only/private documents
   via keywords, semantics, citations, source links, cached snippets and
   conversation history. Include missing/empty OIDC groups, revoked
   memberships, inactive users and changing Guardian ACLs.
5. Deploy the broker by an explicitly approved versioned Ansible PR
   with backup/rollback. No Paperless document permission writes from AI.

No current Bergen-AI or Paperless production configuration is changed by
this PR or by its intended read-only audit.
