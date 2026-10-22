# Native Paperless tags: one catalogue, protected private documents

Status: **feature branch, staged only**, 2026-10-22. No production run of
the new playbook has been observed. This change is deliberately independent
of the Paperless native-chat Nginx/timeout issue.

## Owner-approved policy

All **authenticated human family members** belonging to the pre-existing
`Familie@bergen.intern` group may see **every existing Tag**, whether the
Tag is owned by the administrator or was created by a parent. Children may
see Tag names even if a Tag only happens to occur on a private document;
this is deliberate metadata visibility, not document-content permission.

A single document carries one native M2M set of Tags. On a shared document,
every user permitted to see the document sees its current Tag assignments,
subject to the separately granted tag-read capability. All updates to that
document's Tags therefore become visible to other permitted viewers.
This is **not** copying or synchronizing Tags between different Documents.

Tag visibility does **not** grant `view_document`, `change_document`,
`delete_document`, or `change_tag`. Parents retain their existing rights
to edit shared documents; children's ability to modify a document remains
governed by document-level `change_document` permissions, not Tag read.
Thomas' private Documents remain inaccessible to Nadja and to children.
Nadja's private Documents remain unaffected.

**Important:** The Paperless UI's generic "default view groups" setting
also applies to newly created *Documents*. Never use it to implement this
Tag-only sharing policy; it could expose private documents.

## Controlled implementation

- Read-only by default: `ansible/playbooks/manage-paperless-family-shared-tags.yml`.
- Owner-scoped script:
  `ansible/files/paperless/reconcile_family_shared_tag_visibility.py`.
- Targets only existing unprivileged Paperless-ngx 3.3.0 in CT126. Refuses
  unexpected guest, bad group membership, absent private Thomas/Nadja boundary,
  unexpected tag count, unbounded tag/document populations or unreviewed version.
- The initial audit discovers the *total* existing Tag count; **do not
  confuse Thomas' 38 visible Tags with the database total**. The apply
  mode requires the exact observed total as an explicit pinned argument.
- Apply adds precisely `documents.view_tag` as a model-level right to
  `Familie@bergen.intern` and `view_tag` object permission from that
  group to each existing Tag. No other model/object rights are changed.
- The script takes before/after snapshots of effective document view,
  change and delete rights for all family members, document owners,
  document group ACL rows, and **all document–Tag assignments**, and
  verifies Thomas' private-document denial to Nadja remains unchanged.
  The change runs inside one database transaction and raises/rolls back
  on a failed postcondition.
- No passwords, personal Tag names, document IDs, content or private
  metadata are logged. Output includes aggregate population and gap counts.

## Default audit

In a **separate clean worktree** or a clean detached checkout from main,
retrieve `feat/paperless-family-visible-all-tags-20261022` and run:

```bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-paperless-shared-tags"
  test -d "$WT" || git -C "$BASE" worktree add --detach "$WT" main
  test -z "$(git -C "$WT" status --porcelain)"
  git -C "$WT" fetch origin feat/paperless-family-visible-all-tags-20261022
  git -C "$WT" switch --detach origin/feat/paperless-family-visible-all-tags-20261022
  cd "$WT"
  "$BASE/.venv/bin/ansible-playbook" \
    -i ansible/inventory.yml \
    -i "$BASE/ansible/inventory.local.yml" \
    ansible/playbooks/manage-paperless-family-shared-tags.yml \
    --vault-id ai@prompt
)
```

Expected: `AUDIT=READ_ONLY`, `TAGS=<observed count>`,
`FAMILY_MIN_VISIBLE_TAGS_BEFORE=<count>`,
`TAG_GROUP_GRANTS_MISSING_BEFORE=<count>`,
`THOMAS_PRIVATE_DENIED_TO_NADJA=>0`, `CHANGED=False`.

Do not run Apply if a precondition fails, if Tag names should remain secret
from the children, or if membership is unexpected.

## Separately approved apply

Only after reviewing the actual count and verifying a recent CT126 backup.
Example for an **actual observed** count of 38, not a presumption:

```bash
"$HOME/bergen-platform/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$HOME/bergen-platform/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-family-shared-tags.yml \
  --vault-id ai@prompt \
  -e paperless_family_tags_mode=apply \
  -e paperless_family_tags_apply_approved=true \
  -e paperless_ai_catalog_verified_backup=true \
  -e paperless_family_tags_expected_count=38
```

This independently checks for an NFS CT126 backup within 48 hours. A
backup archive is not proof of successful restoration. An apply writes only
the group permission and Tag read grants, and must report unchanged
document ACLs, owners and Tag assignments.

## New Tags and future accounts

This implementation **reconciles existing Tags only**. Newly created Tags
will not automatically receive the family view grant until the reconciler
runs again. The apply is idempotent and can be rerun with the newly
observed Tag count, but no automatic timer is enabled here. A future
root-owned, restricted timer or a reviewed Tag-create hook is needed for
immediate ongoing automatic sharing. Do not alter generic UI default
permissions to work around this.

After apply, sign into native Paperless with Thomas, Nadja and each
child; verify that the Tag catalogue is identical, but document visibility
still differs according to each account's ACL. A family-only Tag appearing
on a private document must not reveal the document through Tag navigation,
counts, search, API, or AI chat.
