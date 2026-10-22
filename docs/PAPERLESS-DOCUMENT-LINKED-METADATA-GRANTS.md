# Paperless 3.3.0: document-derived visibility of correspondents and types

Status (2026-10-22): **staged and not applied**. Separate feature branch.
No Paperless data was changed by the preceding independent READ_ONLY audit.

## Accepted ACL policy

- A family member may see a DocumentType or Correspondent if it is referenced
  by **at least one document that member is permitted to view**.
- Seeing such metadata does not grant the document itself, access to other
  documents carrying the same metadata, or edit/delete privileges.
- Private Thomas documents remain invisible to Nadja and to children.
  Existing Eltern document objects remain invisible to children.
- The already approved 38 family-shared Tags remain a **separate, broader**
  metadata catalogue. Their policy is not changed.
- These metadata rights are granted to **individual users**, not globally
  to the entire family group, to avoid disclosing unrelated metadata.

## Live inventory (read-only, 2026-10-22)

- Paperless documents: **60**; active family users: **3**.
- Document types: **8**; correspondents: **13**.
- Missing effective *user/object* views on already readable documents:
  **9** document type grants and **12** correspondent grants.
  These counts may include the same metadata ID for multiple users.
- Missing model-level rights: **0**.
- Thomas-owned private documents not viewable by Nadja: **9**.
- Children see zero Eltern-group documents and zero Thomas-private documents.

The audit has proved eligibility and the absence of expected model-right
shortfalls; it has not tested how the browser renders the metadata list.

## Code and safeguards

- \`ansible/files/paperless/reconcile_document_linked_metadata_view.py\`
  computes the allowed metadata objects independently per user using native
  \`permitted_document_ids(user)\` and
  \`permitted_object_ids(user, metadata_model, view_perm)\`.
- \`ansible/playbooks/manage-paperless-document-linked-metadata-view.yml\`
  is **read-only by default**, requires exact CT126 confinement, previous
  known ZFS backup-included mount, existing NFS backup younger than 48 hours,
  explicit approval, and the **same five exact live counters** reported in
  the previous audit before any apply.
- Exact write set: \`UserObjectPermission\` granting
  \`view_documenttype\` or \`view_correspondent\` to eligible users, each for
  an object referenced by a document they can view. There are no grants
  to an entire group, to any document, or to other model permissions.
- Django \`transaction.atomic\` encloses all grants, with a read-only
  snapshot of document fields, all document-tag assignments, document user
  and group ACLs, group memberships and model permissions, metadata owners
  and group ACLs. After writes, assert those snapshots are unchanged.
  Also verify the only new metadata user ACL rows are exactly planned
  and that all required metadata is now visible.
- Generic failure details, identifiers, names, document content and
  credentials are never printed. Bounded status/counters only.
- On a failed assertion inside the transaction, all database grants made
  by this script are rolled back.

## Before allowing a write

Use a clean, separate worktree. Retrieve the exact reviewed branch version
from origin and run its unit tests and default **no-write** audit:

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-linked-metadata"
  BRANCH=feat/paperless-document-linked-taxonomy-grants-20261022

  git -C "$BASE" fetch origin "$BRANCH"
  PIN="$(git -C "$BASE" rev-parse FETCH_HEAD)"
  if ! test -d "$WT"; then
    git -C "$BASE" worktree add --detach "$WT" "$PIN"
  fi
  cd "$WT"
  test -z "$(git status --porcelain)"
  git switch --detach "$PIN"

  "$BASE/.venv/bin/python" -m unittest discover -s tests \\
    -p 'test_paperless_document_linked_metadata_grants.py' -v

  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/manage-paperless-document-linked-metadata-view.yml \\
    --vault-id ai@prompt
)
\`\`\`

Expected initial counts: \`TYPE_VIEW_GAPS=9\`,
\`CORRESPONDENT_VIEW_GAPS=12\`, \`DOCUMENTS=60\`, \`FAMILY_USERS=3\`,
\`THOMAS_PRIVATE_DENIED_TO_NADJA=9\`, \`CHANGED=False\`.
Any change in these numbers must be investigated and reviewed before apply.

## Separately authorized one-time apply

The following is an example **only for the exact confirmed current
60/3/9/12/9 live scope**, not a permission to run unattended:

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  cd "$HOME/bergen-platform-linked-metadata"
  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/manage-paperless-document-linked-metadata-view.yml \\
    --vault-id ai@prompt \\
    -e paperless_linked_metadata_mode=apply \\
    -e paperless_linked_metadata_apply_approved=true \\
    -e paperless_ai_catalog_verified_backup=true \\
    -e paperless_linked_metadata_expected_docs=60 \\
    -e paperless_linked_metadata_expected_family_users=3 \\
    -e paperless_linked_metadata_expected_type_gaps=9 \\
    -e paperless_linked_metadata_expected_correspondent_gaps=12 \\
    -e paperless_linked_metadata_expected_thomas_private=9
)
\`\`\`

On a successful first apply expect 9 new type and 12 new correspondent
per-user object read grants, zero remaining gaps and exactly unchanged
Document ACLs and privacy invariants. Read-only rerun should independently
confirm \`TYPE_VIEW_GAPS=0\` and \`CORRESPONDENT_VIEW_GAPS=0\`.

## Limitations / future policy

This **one-time** grant plan does not automatically detect new imported
documents, newly created metadata or new family members. It also does not
revoke grants if a previously shared document becomes private. Such stale
rights can leave metadata **names** visible, though never grant document
access. For a strict continuous "visible if and only if referenced by a
document I can currently read" policy, implement separately a provenance-
tracked, per-user reconciliation with tested revocation semantics after
re-review. Do not turn this script into an unattended timer.

The normal Paperless browser should be tested after approval using all
three actual identities. This does not fix the unrelated browser native-chat
streaming error; diagnose that separately.
