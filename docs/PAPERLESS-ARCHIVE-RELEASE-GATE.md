# Paperless archive preflight and main promotion gate

Status, 2026-10-16: **protected same-Btrfs-subvolume NAS archive worker staged but disabled**. No production archive-move gate, inbox source deletion, or 30-day purge is active. Paperless remains outside `main` until the authorized import -> journal -> archival location change and the separately gated safe deletion after proven recoverability have passed live tests.

An **atomic protected archive location change** is not conditional on an immediately preceding backup. The original PDF continues to exist on NAS. **Irreversible expiry/purge** requires a tested, recoverable backup of Paperless + NAS archives + journals as an independent gate. No `archive-move.<site>.enabled` flags are to be created by any audit.

## Verified topology and evidence

- Proxmox LXC 126 is unprivileged. The 32 GiB ZFS rootfs is
  local-zfs:subvol-126-disk-0. The 100 GiB data volume is
  local-zfs:subvol-126-disk-1 at /srv/bergen-paperless with backup=1.
  A rename across the two ZFS datasets cannot be atomic.
- Synology homes is Btrfs subvolume 437; paperless-scan is subvolume
  7446. Both reside on /volume1 but are separate device/subvolume
  boundaries. Direct cross-subvolume rename is not atomic.
- The /volume1/paperless-scan ACL explicitly grants paperless-sync
  extensive access. This does not prove that the account has minimal
  rights or effective rights within each LDAP home. Review each scope.
- The 2026-10-15 03:00:12 vzdump archive was manually verified against
  the live LXC SHA-256 for both private DELETED_BY_USER journal files.
  Matching hashes establish this narrow backup evidence, not a fresh
  restore or purge entitlement.

## Reproduce the read-only checks

On bp-controller, with the normal ignored inventory and NAS settings:

    python3 -m unittest discover -s tests -p 'test_paperless_vzdump_deletion_journals.py' -v

    ansible-playbook \
      -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/audit-paperless-archive-preflight.yml \
      --vault-id paperless@prompt \
      -e @ansible/vars/paperless.vault.yml \
      -e @ansible/vars/paperless-synology.local.yml \
      -e paperless_backup_archive=/mnt/pve/bergen-synology-backup/dump/vzdump-lxc-126-2026_10_15-03_00_12.tar.zst \
      --syntax-check

Remove --syntax-check only for the READ-ONLY runtime audits.
The audit checks explicit LXC identity, rootfs and mp0 coverage, direct
NFS mount, exact archive path, and both expected journal hashes without
printing journal contents or extracting members to disk. It reuses the
existing mount, native Synology ACL and archive preflight playbooks.

A successful preflight execution is NEVER a release approval. The NAS
archive preflight deliberately reports blockers for unimplemented
sender versioning and source/quarantine handling.

## Mandatory criteria for first archive-move release and main promotion

1. Every imported scan is reconciled with a live Paperless document ID,
   SHA-256, effective owner/group and visibility. Deliberately deleted
   Paperless documents are never implicitly reimported.
2. Filename reuse, successive identical names, rsync destination
   collisions and repeated/partial receipts have collision-free versioned
   identities with replay protection and exhaustive regression tests.
3. Private, root-controlled same-site NAS archives receive the original
   PDF through durable `renameat2(RENAME_NOREPLACE)` on the exact same Btrfs
   subvolume, following a freshly verified Paperless import and under
   the configured shared sender lock. No cross-device rename or copy-unlink
   fallback. The distinct /tmp-only v2 copy-unlink fixture is not a live path.
4. The scan source entry vanishes through the atomic rename **but the
   original file is preserved in the protected archive**. A crash at the
   prepared/rename/archived journal boundary must be detectable and safely
   reconciled; mismatches block further attempts. No silent replay.
5. Initial release scope (2026-10-15): the archived NAS original
   is retained for **at least 30 full days**, and indefinitely until a
   separately reviewed expiry worker is explicitly enabled. No automatic
   quarantine purge is required for the first archive-move release.
   Retention starts only at the durable ARCHIVED timestamp, not the
   scan time, file mtime or Paperless import date. A later expiry worker
   must independently verify backup/restore health and exact eligible
   journal states at purge time; this is a separate release gate.
6. Four privacy scopes pass effective DSM and Paperless ACL tests. A
   controlled live PDF canary, nonce-bound sender/import proof and recovery
   tests must pass before a single protected archive move is released.
   Independent **backup/restore** is a mandatory gate for the later
   destructive 30-day expiry worker (and for full eventual promotion).
7. Merge the Paperless feature stack (PR #60 or successor) into main
   only after these criteria pass. Read-only checks do not bypass them.

This historical two-journal verifier is intentionally pinned to
documents 15 and 26; it does not discover new journals and must not
serve as the future general backup gate for retention purges.

## v2 live readiness audit (16.10.2026, not an archive gate)

`ansible/playbooks/audit-paperless-v2-live-readiness.yml` reads the NAS
v1/v2 sender history via the existing restricted SSH + `sync.lock` path and
executes the live Paperless v2 import/owner/ACL exporter through `pct exec 126`.
`summarize_paperless_v2_live_readiness.py` verifies the output framing,
rejects malformed/inconsistent event inventories and prints **anonymous
counts only**, even if v2 identity fields are present. It **does not** match
a specific NAS SENT receipt to a specific imported PDF and **never** grants
archival, source deletion or purge. There is no deployment/activation step.

Controller checks on the exact PR branch:

    python3 -m unittest discover -s tests -p 'test_paperless_v2_live_readiness.py' -v
    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \\
      ansible/playbooks/audit-paperless-v2-live-readiness.yml \\
      --vault-id paperless@prompt \\
      -e @ansible/vars/paperless.vault.yml \\
      -e @ansible/vars/paperless-synology.local.yml --syntax-check

After those pass, omit `--syntax-check` for the live **read-only** evidence
collection. No candidate selection or NAS worker enablement occurs. If the
NAS has no live v2 SENT events, this is an expected development blocker,
not a reason to fabricate a receipt or downgrade the authorization contract.


## Read-only v1 archive dry-run candidate list (16.10.2026)

The current sender uses v1 (24 SENT and no v2 event). The candidate list
includes only NAS originals still present with a corresponding live-verified
Paperless IMPORTED object. This does not authorize a move or purge.

The read-only playbook `ansible/playbooks/list-paperless-v1-archive-candidates.yml`
combines a locked NAS source/receipt/hash scan with the Paperless import and
effective owner/ACL exporter. The controller tool
`list_verified_archive_candidates.py` reuses the reviewed
`select_one_verified_archive_move.py` validation contract for each matching
original. Ansible suppresses raw receipt, document-ID and digest output.
Only the scope/original PDF filename is deliberately visible in the
operator terminal. A mismatch blocks or omits selection.

On bp-controller, in the isolated PR #81 worktree:

    python3 -m unittest discover -s tests -p 'test_paperless_list_verified_archive_candidates.py' -v

    ansible-playbook -i ansible/inventory.yml \
      -i ~/bergen-platform/ansible/inventory.local.yml \
      ansible/playbooks/list-paperless-v1-archive-candidates.yml --syntax-check

After passing, run the same playbook without --syntax-check with
the ignored site variables and Vault:

    ansible-playbook -i ansible/inventory.yml \
      -i ~/bergen-platform/ansible/inventory.local.yml \
      ansible/playbooks/list-paperless-v1-archive-candidates.yml \
      --vault-id paperless@prompt \
      -e "@$HOME/bergen-platform/ansible/vars/paperless.vault.yml" \
      -e "@$HOME/bergen-platform/ansible/vars/paperless-synology.local.yml"

Expected markers: `V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES N`,
`CANDIDATE "Scope/Filename.pdf"`, `CANDIDATE_AUDIT_COMPLETE`,
`NO_FILES_CHANGED`, `ARCHIVE_NOT_AUTHORIZED`, `PURGE_NOT_AUTHORIZED`.

A listed candidate is a snapshot in time, not approval to move it.
Never create site release gates or use --commit from this report.
A fresh one-file dry-run must repeat the checks before any later approval.


## Verified 15/26 deletion lifecycle in the v1 candidate list (16.10.2026)

The first v1 list attempt stopped at \`export_imported_scans.py\`, because
two historically \`IMPORTED\` bridge receipts still exist after deliberate
deletions. The LXC read-only diagnostic returned
\`PAPERLESS_DOCUMENT_NOT_FOUND\`; no receipt was edited or excused.

The independent **live** \`audit-paperless-import-lifecycle-15-26.yml\`
then passed with \`PAPERLESS_LIVE_IMPORTED 22\`, \`NAS_SENT_VERIFIED 22\`,
\`DELETED_BY_USER 2\`, \`IMPORT_LIFECYCLE_RECONCILED\`,
\`NO_RECEIPTS_CHANGED\`, \`NO_FILES_CHANGED\`. It checked the two specific
published/hashed user-deletion journals, their NAS source absence, and
live Paperless absence; all other 22 sources matched real imports.
It did **not** grant archive authorization.

The corrected \`list-paperless-v1-archive-candidates.yml\` imports this
full audited playbook, requiring a fresh successful run. It sets
\`paperless_lifecycle_quiet=true\`, so the imported lifecycle check
suppresses raw receipt/identifier logs; otherwise its normal standalone
output is unchanged. The pure controller tool
\`list_verified_lifecycle_archive_candidates.py\` accepts only the
registered live NAS inventory, the live status-tagged lifecycle evidence
and the success report from that run. It validates that deletions are
**exactly** pinned records 15 and 26, strips only those two
\`DELETED_BY_USER\` records, then reuses the existing exact v1 sender/import
selector for **all** remaining files. Unknown deletion, missing audit
marker, mismatch, duplicate or extra source blocks the whole list.
Candidates are moment-in-time scope/original PDF names only, *not*
authorization to move the files.

First in \`~/bergen-platform-pr81\` after a clean fast-forward:

    python3 -m unittest discover -s tests -p 'test_paperless_list_verified_lifecycle_archive_candidates.py' -v

    ansible-playbook -i ansible/inventory.yml \
      -i ~/bergen-platform/ansible/inventory.local.yml \
      ansible/playbooks/list-paperless-v1-archive-candidates.yml --syntax-check

Only after success may the operator rerun the candidate playbook without
\`--syntax-check\`, using \`--vault-id paperless@prompt\` and the two
site-local var files. Expected success: 22 \`CANDIDATE\` rows,
\`DELETED_BY_USER_EXCLUDED 2\`, \`CANDIDATE_AUDIT_COMPLETE\`,
\`NO_FILES_CHANGED\`, \`ARCHIVE_NOT_AUTHORIZED\`, \`PURGE_NOT_AUTHORIZED\`.
The count 22 is expected from the prior separate live audit, **not**
yet proof of this newly modified playbook; verify actual output.

IMPORTANT: the existing \`archive-paperless-verified-import.yml\`
still invokes the original strict \`export_imported_scans.py\`; it is
**not** ready for the one-file dry-run while historical imported/deleted
receipts exist. Adapt that path to the independently verified lifecycle
separately, with fresh tests and without a commit gate, before attempting
any source dry-run. Do not create release flag files or activate purge.


## First strictly non-committing one-file v1 NAS archive preview (16.10.2026)

The first lifecycle-aware candidate inventory live run succeeded:
`V1_VERIFIED_ARCHIVE_DRY_RUN_CANDIDATES 22`,
`DELETED_BY_USER_EXCLUDED 2`,
`CANDIDATE_AUDIT_COMPLETE`, `NO_FILES_CHANGED`,
`ARCHIVE_NOT_AUTHORIZED`, `PURGE_NOT_AUTHORIZED`;
Ansible: `venombox ok=17 changed=0 failed=0 skipped=1`.
Distribution: `Eltern` 7, `Familie` 9, `Privat/thomas` 6,
`Privat/nadja` 0.

**Do not run the old `archive-paperless-verified-import.yml` yet.**
It still uses `export_imported_scans.py` and fails because two historical
`IMPORTED` receipts are legitimately `DELETED_BY_USER`.

New, separate **dry-run only** entrypoint:
`ansible/playbooks/preview-paperless-one-v1-archive.yml`.

It imports the full 15/26 deletion lifecycle audit with suppressed private
proof output; uses the reviewed
`select_one_verified_lifecycle_archive_preview.py` to require precisely one
currently live `IMPORTED` source and produce the private per-file proof; verifies
root ownership and current exact source-code SHA-256 of the staged NAS worker;
**requires all three release gate files absent**; calls that NAS worker
with `--state-parent` and exact `--only` and **without any `--commit` option**.
The NAS worker locks the sender state and repeats source signature, v1 SENT
receipt, file SHA-256, and protected same-device destination checks.
It must return `ARCHIVE_DRY_RUN` plus `ARCHIVE_PURGE_DISABLED`.
The controller suppresses receipt hashes and reports only
`ARCHIVE_DRY_RUN_VERIFIED`, `SOURCE_UNCHANGED`, `NO_RECEIPTS_CHANGED`,
`NO_FILES_CHANGED`, `ARCHIVE_NOT_AUTHORIZED`, `PURGE_NOT_AUTHORIZED`.
No archive or purge is authorized by a passing preview.

After updating the dedicated PR worktree, run tests and syntax check first:

    python3 -m unittest discover -s tests -p 'test_paperless_one_v1_archive_preview.py' -v

    ansible-playbook -i ansible/inventory.yml \
      -i ~/bergen-platform/ansible/inventory.local.yml \
      ansible/playbooks/preview-paperless-one-v1-archive.yml --syntax-check

Only after test and syntax acceptance, select **one original Scope/Filename.pdf
from the previous live candidate output** and use the operator's ignored
site-local vars and vault:

    ansible-playbook -i ansible/inventory.yml \
      -i ~/bergen-platform/ansible/inventory.local.yml \
      ansible/playbooks/preview-paperless-one-v1-archive.yml \
      --vault-id paperless@prompt \
      -e "@$HOME/bergen-platform/ansible/vars/paperless.vault.yml" \
      -e "@$HOME/bergen-platform/ansible/vars/paperless-synology.local.yml" \
      -e '{"paperless_archive_only":"Familie/EXAMPLE.pdf","paperless_archive_commit":false}'

The example filename is placeholder-only. Do not use it without an exact
live candidate record. Never set `paperless_archive_commit=true`.

**Important:** If the staged NAS worker is absent, has a different hash,
or any commit gate exists, the preview **fails closed**. Do not automatically
stage or activate it. Investigate and separately review the disabled worker
stage before any code upload to MountainCloud.

Production `renameat2(RENAME_NOREPLACE)` remains a distinct release
milestone requiring the appropriate acceptance tests and explicit
per-site administrative authorization; 30-day purge is a separate
later step with verified restore, not implied by archival relocation.
