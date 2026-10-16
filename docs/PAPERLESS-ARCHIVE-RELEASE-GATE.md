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


## One-PDF live-move release preparation — NOT authorized (16.10.2026)

The first complete lifecycle-aware preview of
one operator-selected PDF from the verified candidate list passed:
`ARCHIVE_DRY_RUN_VERIFIED`, `SOURCE_UNCHANGED`,
`NO_RECEIPTS_CHANGED`, `NO_FILES_CHANGED`,
`ARCHIVE_NOT_AUTHORIZED`, `PURGE_NOT_AUTHORIZED`.
Ansible: venombox `ok=22 changed=0 failed=0 skipped=1`.
The staged NAS worker matched the OLD reviewed SHA-256, all gates absent.

**Important newly discovered authorization risk:** The original
`archive-move.<site>.enabled` semantics accepted *any* root-owned, 0600
file and did not bind it to a source or live proof. This is too broad even
for a single controlled pilot. The revised
`synology_same_volume_archive_move.py` therefore requires **canonical
JSON** with root:root 0600 ownership and a fixed schema, binding exact
site, scope, original PDF filename, NAS SENT receipt identity,
Paperless bridge receipt, document SHA-256 and positive Paperless document
ID. Its issue/expiry epoch timestamps must provide no more than 15
minutes of validity, and the issuing time may not lie in the future.
An empty site flag or any wrong, stale or otherwise mismatched manifest
is refused. The legacy global gate remains prohibited. On production
commit, the worker reads the protected manifest *before* touching source
or archive and rechecks source SHA/signature/import proof under sender
lock before any durable write. The standalone
`build_one_archive_release_manifest.py` is **pure**: it produces canonical
bytes from one separately validated controller proof. It has NO CLI,
no file writes, and cannot enable any gate.

**No new worker has been staged yet.** The reviewed on-NAS worker
was accepted for the dry-run but must be updated through the already
disabled-only staging playbook after all tests and security review, and
then previewed again. No activation flag, production PDF move or purge
may be created during this preparation.

**Blocker for a correct post-move lifecycle**: The current v1 audit
`audit-paperless-import-lifecycle-15-26.yml` assumes all live imported
PDF originals are still in the source folders. A successful rename would
yield 21 original source files and 22 live imports; the current lifecycle
matching would fail. Before any real move, implement and test a
read-only archive-journal/live-inode/hash-aware lifecycle state:
every live Paperless import must map **exclusively** to either a current
NAS source + SENT receipt, **or** a protected archive file plus a complete
`ARCHIVED` journal. The two pinned `DELETED_BY_USER` histories must
remain distinct from both states. A `PREPARED`-only journal, duplicate
live source+archive, vanished inode, wrong SHA, unexpected ACL or new
unknown source should fail closed. Candidate lists and future previews
must omit already archived documents but preserve reconciliation.
A post-move verification must additionally verify the same NAS inode,
same Btrfs device, restored original PDF bytes, protected archive
permissions and live Paperless access, without treating that check as
an expiry/purge approval.

Release order:
1. Unit tests for the tightened worker + manifest and disabled-only
   staging/syntax review.
2. Re-stage reviewed worker while all gates are ABSENT. Re-run the
   same single-PDF dry-run with the newly staged SHA-256.
3. Implement and live-read-only-test archive-aware reconciliation
   (zero ARCHIVED should reproduce the current 22 live-original result).
4. Review effective native DSM ACLs and subscriber/scanner write
   quiescence; validate failure/restart/recovery cases.
5. Prepare exact-one-file short-lived gate installation, explicit
   approval, a single `renameat2(RENAME_NOREPLACE)` attempt and
   fail-closed gate revocation in a separately reviewed release playbook.
   Approval for the chosen PDF must be sought *again* immediately before
   executing any of these mutating steps.
6. Re-audit the new source/archive state and Paperless visibility. Any
   incomplete journal requires manual reconciliation, never blind retry.

A private archive rename retains the original, and **does not** require
an immediately preceding external backup. A future destructive purge
does require independently tested backup plus restore and a separate
explicit release. No purge feature is enabled or developed here.


## Archive-aware read-only lifecycle audit — implementation pending live test

Updated 2026-10-16 after the hardened worker's *second* non-committing
NAS preview passed (`venombox ok=22 changed=0 failed=0 skipped=1`,
`ARCHIVE_DRY_RUN_VERIFIED`, `NO_FILES_CHANGED`,
`ARCHIVE_NOT_AUTHORIZED`, `PURGE_NOT_AUTHORIZED`).

The new restricted NAS reader
`ansible/files/paperless/audit_synology_completed_archive_moves.py`
takes the shared `sync.lock` and inspects every protected archive
journal. A `PREPARED` without `ARCHIVED`, an unknown/orphan entry,
a conflicting/corrupt event, or an unexpected PDF in the protected
archive **blocks** the entire audit. For each completed journal pair it
matches the root-owned reference worker's v1 sender receipt, ensures the
scan-inbox original is absent, verifies same archive filesystem and
original inode, size, mtime and SHA-256 of the PDF (ctime may legitimately
advance across the rename), and produces a restricted archived-proof
record. The two permanent `DELETED_BY_USER` journals remain separate.
There is no write path, and only `NO_FILES_CHANGED` marks completion.

`audit-paperless-import-lifecycle-15-26.yml` now runs the archived
reader before the full controller join. The updated
`match_paperless_import_lifecycle_15_26.py` requires every live
Paperless `IMPORTED` receipt to be backed by **exactly one** current
live NAS source **OR** a complete verified archive. Both and neither
fail closed. Distinct output:
`NAS_SENT_VERIFIED N`,
`NAS_ARCHIVED_VERIFIED M`,
`NAS_CURRENT_ORIGINALS_VERIFIED N+M`,
`PAPERLESS_LIVE_IMPORTED N+M`.
It continues to require precisely the existing two pinned
`DELETED_BY_USER` histories (IDs 15 and 26).

`list-paperless-v1-archive-candidates.yml` and
`preview-paperless-one-v1-archive.yml` pass the new archived proof.
The candidate listing excludes archived originals even though their
Paperless documents remain live. An already archived PDF cannot
be offered for another archive preview.

**Pending acceptance:** The new scripts and updated playbooks have
only been prepared in the feature PR. Run the new synthetic suite
`test_paperless_archived_lifecycle_reconciliation.py` along with the
existing v1 lifecycle, candidate and preview suites; syntax-check all
three updated playbooks. Then run the revised full audit **read-only**
against the current zero-archived live NAS. Expected baseline:
22 source originals + 0 archived = 22 live imports; exactly
2 historical user deletions. Do NOT create any release gate or run
`--commit` after just a successful zero-archive audit. A controlled
21-source+1-archive scenario still requires independent acceptance
after an explicitly approved one-PDF move.

**The first real rename is STILL BLOCKED** until independent effective
DSM rights/writer-quiescence, crash-recovery validation and a separately
reviewed, one-shot gate install/commit/revoke process. The previous
pure 10-minute exact-manifest generator is not an activation path.


## Protected archive effective LOCAL (NSS/POSIX) access — pending live test

The operator's **read-only existing protected-site audit** for
\`paperless-scan\` passed on 2026-10-16:

- \`DEVICE_ROOT /volume1/paperless-scan\`,
  \`SOURCE_DEVICE 1048641\`;
- \`PARENT_ACL_STATUS NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT\`;
- \`PROTECTED_ARCHIVE_CANDIDATE EXISTS\`,
  \`PROTECTED_ARCHIVE_EMPTY_TREE_VERIFIED paperless-scan 3\`;
- \`PREPARE_DISABLED\`, \`NO_FILES_CHANGED\`,
  \`ARCHIVE_COMMIT_NOT_AUTHORIZED\`;
- Ansible localhost \`ok=4 changed=0 failed=0\`.

This verifies the existing protected directory tree and static parent ACL
classification, **not** actual effective LDAP users or an SMB session.

New dedicated **nonmutating** follow-up:
\`ansible/playbooks/audit-paperless-synology-effective-archive-access.yml\`
uses the restricted, fixed-site Python reader
\`ansible/files/paperless/audit_synology_effective_archive_access.py\`.
The operator must explicitly name 2–8 distinct real NSS usernames;
there are no guessed/default principals. On MountainCloud a root
orchestrator resolves each identity, then drops UID/GID and initializes
its actual NSS supplementary groups BEFORE probing the protected root,
\`Eltern\` and \`Familie\` directories. It requires the actual
\`paperless-sync\` account to open/list and have write+traverse access,
and EVERY named non-owner account to have NEITHER directory-list nor
write+traverse access. It only opens directories, lists entries and
queries \`os.access\`; **no create/rename/unlink attempts**. Ansible
suppresses identities and private filesystem output and prints status
and counts only. Any missing NSS user, wrong group/UID, denied owner or
unexpected nonowner permission BLOCKS release.

Operator acceptance order: offline
\`tests/test_paperless_effective_protected_archive_access.py\` plus Ansible
syntax check; select real usernames after verifying NSS resolution; run
the playbook with ignored NAS/vault vars plus
\`-e '{"paperless_archive_denied_users":["<first-confirmed-NSS-user>","<second-confirmed-NSS-user>"]}'\`.
Bracketed names are placeholders, not actual account recommendations.
Expected verdict \`ARCHIVE_LOCAL_OWNER_ACCESS_VERIFIED\`,
\`ARCHIVE_LOCAL_NEGATIVE_IDENTITIES_DENIED N\`,
\`SMB_EFFECTIVE_ACCESS_NOT_TESTED\`, \`NO_FILES_CHANGED\`,
\`ARCHIVE_COMMIT_NOT_AUTHORIZED\`.

**Remaining material limitation:** A local root-orchestrated UID/GID
test does NOT demonstrate what a DSM/SMB session can do, nor can it
prove the inability to rename/remove the *protected archive entry*
without a controlled disposable test. Native parent ACL inspection
above remains necessary, and a separate isolated canary protocol is
required before first live source rename. Existing real protected
directories and documents MUST NOT be renamed to test permissions.
No broad site gate or destructive purge is enabled.


## 2026-10-16 operator scope change: activate GROUPS FIRST

The operator authorized archive moves of the previously reconciled 22 live
v1 originals and then narrowed the immediate rollout: **activate group
directories first**, i.e. 7 in \`Eltern\` and 9 in \`Familie\` on the
\`paperless-scan\` Btrfs subvolume. The 6 \`Privat/thomas\` originals are
**not** in this first activation; \`Privat/nadja\` has zero candidates.
The two pinned \`DELETED_BY_USER\` records remain excluded. No purge is
authorized.

Site readiness evidence: the protected \`paperless-scan\` archive tree
was read-only audited empty with secure native parent ACL status,
and read-only NSS/POSIX tests denied listing/write+traverse to two named
nonowners while positively verifying the service account. An SMB
login by one family user allowed a known-path \`cd\` but \`ls\` returned
\`NT_STATUS_ACCESS_DENIED\`. This proves denied enumeration, NOT universal
SMB content or directory-entry rename/delete rights. The operator chose
not to repeat SMB listing tests for additional users.

A separate \`homes\` read-only prepared-site audit also passed:
\`DEVICE_ROOT /volume1/homes\`, \`SOURCE_DEVICE 47\`,
\`PROTECTED_ARCHIVE_EMPTY_TREE_VERIFIED homes 4\`,
\`PARENT_ACL_STATUS NATIVE_PARENT_NO_OBVIOUS_DELETE_GRANT\`,
\`PREPARE_DISABLED\`, \`NO_FILES_CHANGED\`,
\`ARCHIVE_COMMIT_NOT_AUTHORIZED\`; localhost \`ok=4 changed=0 failed=0\`.
This does NOT grant a private-directory rollout.

### Controlled GROUP-only exact-one-PDF release — awaiting acceptance

Prepared PR code, **not yet installed or run**:

- \`ansible/files/paperless/synology_one_group_archive_release.py\`
  is a root-owned NAS one-shot wrapper. It accepts only \`Eltern\`
  and \`Familie\`, a controller-selected exact original and a private
  import proof. It creates exactly one root-owned, 0600,
  600-second canonical exact-PDF manifest at
  \`archive-move.paperless-scan.enabled\` with \`O_EXCL\`, invokes the
  previously staged archive worker as unprivileged \`paperless-sync\`,
  and removes the gate in \`finally\`. It rejects any existing
  site/global release flag, never creates an all-site authorization,
  and never invokes a purge. If the process is interrupted with SIGKILL,
  a surviving exact gate expires; investigate/remove safely before retry.
- \`ansible/playbooks/stage-paperless-one-group-archive-release-runner.yml\`
  stages only reviewed root-owned code with all three gates absent.
- \`ansible/playbooks/commit-paperless-one-group-v1-archive.yml\`
  imports the full independent 15/26 reconciler BEFORE selecting a
  controller-verified one-PDF proof; checks exact staged NAS source
  and runner hashes and absent gates; requires the explicit **typed**
  \`paperless_archive_commit: true\` flag; invokes the one-shot root
  wrapper; then independently repeats the FULL lifecycle audit to
  require 22 live Paperless documents, exactly two pinned deletions,
  the NAS source count reduced by one, the archived count increased by
  one and **all gates absent**. Stops at any mismatch.
- \`tests/test_paperless_group_archive_release.py\` exercises proof
  validation, group-only restrictions, preexisting gate refusal and
  synthetic temporary gate creation/revocation on success/failure.
  These tests are not yet proven green on the controller.

**Operational order**: operator first runs the new offline tests and
Ansible syntax checks. Stage the new disabled runner ONLY after test
acceptance; new staging changes root-owned code but no PDFs or archive
receipts. Independently choose one already proven group PDF and run a
SINGLE production commit as a canary. Examine complete new 21+1 live
lifecycle before deciding on the other 15. Every subsequent source
requires a fresh full proof, one-shot gate, atomic no-overwrite rename,
revocation and full post-move audit. A failed or partial journal blocks
all subsequent operations pending human recovery. No automated
source-loop has been released yet; do not run blind for-loops of
\`--commit\` or the historical incompatible archive playbook.

**Important:** The operator's approval of archive relocation does NOT
allow bypassing security/preflight/roll-forward checks, enabling
permanent site flags, deleting archive originals, or applying this
GROUP-only code to private user folders.
