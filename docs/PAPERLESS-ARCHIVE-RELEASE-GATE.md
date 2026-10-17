# Paperless archive preflight and main promotion gate

Status, 2026-10-16: **one approved exact-file group-only production archive relocation completed and independently reconciled**; the reviewed worker and root release runner remain staged, with all temporary commit gates absent. No production archive-move gate, inbox source deletion, or 30-day purge is active. Paperless remains outside `main` until the authorized import -> journal -> archival location change and the separately gated safe deletion after proven recoverability have passed live tests.

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


## 2026-10-16 first group-only commit blocked before archived journal

Operator authorized exactly `Familie/Bergen-Platform-fuer-Dummies.pdf` after
the 714-test offline suite, read-only 22/0 lifecycle, disabled runner staging,
candidate inventory, one-PDF dry run, and commit syntax checks. The first live
commit returned a nonzero status in the `no_log` one-shot task. **DO NOT
RETRY** without a new review and explicit authorization.

Independent post-failure checks found all three release gates absent and the
read-only lifecycle fully reconciled with 22 remaining NAS SENT originals,
0 archived originals, 22 live Paperless imports, and 2 journaled user
deletions. No `PREPARED` or `ARCHIVED` journal was reported. These checks
demonstrate no completed or partly journaled move in the audited state; they
do not identify the exact swallowed command error.

A concrete release-path defect was found in code review: the root runner
created a root:root `0600` site manifest but launched the archive worker
after dropping privileges to `paperless-sync`; the worker attempted to
`os.open` the manifest by pathname, ordinarily resulting in permission
denied. The defect was not caught by the synthetic wrapper tests, which
mocked the subprocess and did not check the root-to-service-user read boundary.

**Follow-up branch fix, pending operator tests and staging:** root opens the
exact release manifest read-only, passes that file descriptor through
`subprocess.run(pass_fds=...)` across privilege drop, and the restricted
worker uses `os.pread` only after confirming the descriptor matches the
actual root-owned, `0600` pathname inode/size/mode/ownership and the
fresh proof. Missing, closed or unrelated descriptors fail closed.
The old unprivileged path-open is removed. No `chmod`, broad gate, manual
receipt edit, or purge workaround is permitted.

Before any reauthorization: pull the updated PR branch, run all offline
Paperless tests, syntax-check the two disabled-only staging playbooks,
stage the **worker and release runner** (code only, gates absent), independently
verify staged SHA-256, repeat the live read-only lifecycle and one-document
preview, and review potential remaining causes. Any new productive commit
requires a new explicit one-document authorization. Do not run it from
this note.


## 2026-10-16 independently reconciled first completed group-only archive

**Canary:** `Familie/Bergen-Platform-fuer-Dummies.pdf`, the one
explicitly reauthorized group original. After the read-only
post-failure 22-source/0-archive audit, the root-to-`paperless-sync`
protected manifest descriptor fix was staged on NAS for both worker and
runner, always with all three release gates absent.

Operator verified 717/717 `test_paperless_*.py` offline tests; the
archive worker, one-group runner and one-group commit Ansible syntax
checks; disabled-only worker staging (`localhost ok=13 changed=3 failed=0`)
and runner staging (`localhost ok=13 changed=3 failed=0`);
a fresh 22-source/0-archive live read-only lifecycle; and a successful
exact-one-PDF no-write preview (`venombox ok=27 changed=0 failed=0`,
`ARCHIVE_DRY_RUN_VERIFIED`, `ARCHIVE_NOT_AUTHORIZED`,
`PURGE_NOT_AUTHORIZED`). A **new explicit one-file authorization**
was obtained prior to the live commit.

The one-shot production `commit-paperless-one-group-v1-archive.yml`
completed successfully: `venombox ok=54 changed=1 failed=0 skipped=2`
with `ONE_GROUP_PDF_ARCHIVE_COMPLETED`,
`POST_MOVE_LIFECYCLE_RECONCILED`, `ALL_RELEASE_GATES_ABSENT`, and
`ARCHIVE_PURGE_DISABLED`. The committed `renameat2(RENAME_NOREPLACE)`
is backed by one complete protected archive journal and unchanged
live Paperless visibility.

A **separate subsequent read-only** execution of
`audit-paperless-import-lifecycle-15-26.yml` passed:
`venombox ok=19 changed=0 failed=0`;
`NAS_SENT_VERIFIED 21`, `NAS_ARCHIVED_VERIFIED 1`,
`NAS_CURRENT_ORIGINALS_VERIFIED 22`,
`PAPERLESS_LIVE_IMPORTED 22`,
`ARCHIVED_LIVE_IMPORTED Familie document 8`,
`DELETED_BY_USER 2`,
`IMPORT_LIFECYCLE_RECONCILED`, `ARCHIVE_NOT_AUTHORIZED`,
`NO_RECEIPTS_CHANGED`, `NO_FILES_CHANGED`.
The 21 originals still in source plus one archived original reconcile
to the same 22 existing Paperless documents. This independently
detects incomplete archive journals, missing inodes and mismatched
hashes; it is not an independent off-NAS restore test.

**Remaining gates:** No authority to move the other 15 remaining
group-scope candidates, to activate permanent site archive flags,
to touch either private home scope, to automate batches, or to
remove/purge any archived PDF after 30 days. No authority to merge
Paperless into `main` until all separately required recovery,
DSM/SMB rights and irreversible-retention gates have been met.
Do not imply full DSM/SMB effective deletion/rename-denial from the
successful POSIX/NSS and lifecycle evidence alone.

**Audit script caution:** The historical
`audit_synology_archive_entry_protection.py` currently inspects
`source/.paperless-archive`, whereas the active protected group
archive uses the sibling `.bergen-paperless-archive` directory.
Its findings must not be presented as proof of effective native
ACL or directory-entry rename/delete protection for the active
protected archive. Align the read-only auditor with the deployed
protected-path contract and test it before reuse.

## 2026-10-16 protected archive native ACL auditor path correction — pending operator acceptance

The previously available `audit-paperless-synology-archive-entry-protection.yml`
wrongly inspected `source/.paperless-archive`. This **does not represent**
the production same-Btrfs-subvolume archive used for the first group canary.
The existing live archive and import receipts were not changed.

The corrected read-only
`audit_synology_archive_entry_protection.py` uses the deployed root-owned
archive worker's `_validated_protected_scope` resolver and derives the
exact `paperless-scan/.bergen-paperless-archive` and
`homes/.bergen-paperless-archive` hierarchies. It audits the native DSM
ACL grants of each relevant *entry parent*:
both site roots, protected archive roots, scope directories,
the `Privat` intermediate directory for homes, and every existing
`YYYY-MM` archive directory. It rejects unexpected scope entries,
path/device mismatches, symlink/wrong-ownership/mode parents and
unparseable/missing native ACL listings rather than accepting a
legacy scanner-writable path. The audit only opens directories,
queries `synoacltool -get`, and lists existing month names. It does
**not** create, modify, delete, rename or copy a PDF.

The resulting markers must include:
`ACTIVE_PROTECTED_ARCHIVE_PARENTS_AUDITED N`,
`ARCHIVE_ENTRY_PROTECTION_NEEDS_EFFECTIVE_TEST`,
`DSM_SMB_EFFECTIVE_RENAME_NOT_TESTED`,
`ARCHIVE_COMMIT_NOT_AUTHORIZED`,
`NO_FILES_CHANGED`. The static grant classifier reports potential
`BLOCKER` lines for non-admin delete/write+traverse ACEs.
An `ARCHIVE_ENTRY_PROTECTION_NEEDS_EFFECTIVE_TEST` marker explicitly
does **not** mean actual DSM/SMB rename/delete permissions were
negatively tested. Nor is any static ACL finding an archive-move
or irreversible purge approval.

**Acceptance pending:** Pull this branch on `bp-controller`, run
`python3 -m unittest discover -s tests -p
'test_paperless_synology_archive_entry_protection.py' -v`,
and run `ansible/playbooks/audit-paperless-synology-archive-entry-protection.yml`
first with `--syntax-check`, then read-only with standard ignored
inventory/Vault and site-local vars. Review its actual output;
if DSM reports no native ACEs for a protected 0700 directory,
treat it as an explicit audit limitation/fail-closed condition,
not as permission to skip the protected path.

**Separate isolated recovery exercise — not yet executed:**
derive the one archived original only from a freshly validated
`ARCHIVED` journal and live lifecycle; read its PDF through the
least-privileged read-only NAS account into a disposable,
access-restricted scratch copy separate from the original; verify
full SHA-256, expected byte count and PDF structure; independently
verify the original NAS inode/journal/lifecycle unchanged afterward;
discard the scratch. Do not overwrite, rename or remove the
original NAS archive. This demonstrates a single-file read/copy
recovery path only, **not** recoverability from a separately stored
backup, nor permission to enable the 30-day destructive purge.

### 2026-10-16 ACL parser fail-closed live result and candidate remediation

The first live corrected protected-path DSM ACL audit stopped without writes
(`localhost ok=1 changed=0 failed=1`) at
`UNPARSEABLE_ACL_ACE`. **No ACL security verdict was established.**
Documented native `synoacltool -get` output includes
`everyone::allow`, `owner::allow`, `system::allow` and whitespace in
`(level: 0)`, whereas the first parser supported only user/group entries
and `(level:0)`.

The revised parser explicitly supports these DSM principal classes and spacing
with a full-line strict match. Dangerous deletion/write+traverse grants to
`everyone` and `system` are **blockers**, not silently exempted.
`owner::` follows the separately validated actual directory owner.
Unknown roles, unexpected principal names and malformed ACEs remain
fail-closed. Added offline ACL fixtures for special roles, risk classification
and unknown records. **The cause of the production parse error remains a
hypothesis until a successful live run confirms the format.**

Operator acceptance: pull feature branch; rerun full offline suite and
read-only playbook syntax check; retry only the read-only ACL audit.
If the same parser error returns, stop and inspect only sanitized ACL
line structure. Do not weaken parser matching, do not print ACL
principals in public logs, and do not infer permission safety from
a failed audit. No archive move/merge/purge is authorized.

### 2026-10-16 second read-only ACL attempt: native ACL query failed

The updated native ACE parser passed its 726 offline Paperless tests and
the playbook passed Ansible syntax. The second live read-only audit
(`localhost ok=1 changed=0 failed=1`) parsed the three site-root ACEs
for `homes` and then stopped with
`ACTIVE_ARCHIVE_NATIVE_ACL_QUERY_FAILED`, before any global safety
verdict. This is a failed `synoacltool -get` command, **not** proof
of a dangerous grant. The next lexically ordered target is the
`homes` protected archive root.

Added **diagnostics only** to the fail-closed auditor:
`NATIVE_ACL_READ_BLOCKED <site> <kind>
ACTIVE_ARCHIVE_NATIVE_ACL_QUERY_FAILED_RC_<rc>_<class>`.
The class identifies only broad categories such as native ACL absent,
unsupported, access denied, missing path, or unclassified.
No returned raw ACEs, filesystem paths, user/group identities, or
native tool error strings are printed. Unknown causes remain blocked;
the return-code classification is an observation, not permission
to skip an ACL/security check.

After fresh offline tests and syntax acceptance, rerun only the read-only
audit. Record the sanitized diagnostic markers and `PLAY RECAP`.
Do not change Synology ACLs, source/archives, release gates,
journals or 30-day expiry permissions on this basis.

### 2026-10-17 confirmed Linux-mode-only protected archive root

Operator ran an additional root-only read-only diagnostic on Synology
and obtained **exactly**:
`TARGET homes PROTECTED_ROOT`,
`POSIX_OWNER_AND_MODE_VERIFIED`,
`NATIVE_ACL_RC 255`,
`STDOUT_CLASS LINUX_MODE`,
`STDERR_CLASS EMPTY`,
`NO_FILES_CHANGED`.
This explains the preceding
`NATIVE_ACL_READ_BLOCKED homes PROTECTED_ROOT
ACTIVE_ARCHIVE_NATIVE_ACL_QUERY_FAILED_RC_255_UNCLASSIFIED_NATIVE_ACL_ERROR`
without evidence of a dangerous ACL grant. **It is not yet a complete
archive protection verdict.**

The follow-up branch implementation recognizes a Linux-mode-only directory
*solely* when `synoacltool -get` returns **rc=255**, **empty stderr**,
and the **full** exact single-line
`(synoacltool.c, <number>)It's Linux mode` message (with trailing
whitespace permitted). Generic `No ACL`, `permission denied`,
unknown return codes, multiple message lines, unexpected output,
tool timeouts and all other parse failures still block. Only
validated protected child directories with the expected
`paperless-sync` UID, regular directory type and **POSIX 0700**
can be classified as `POSIX_0700_LINUX_MODE`. No ACL is added
or permissions modified.

**Both `homes` and `paperless-scan` site roots must STILL have
independently parsed native DSM ACLs**, protecting their child archive
directory entries from nonadministrator delete-child/rename grants;
a Linux-mode-only site root remains a blocker. The resulting output
reports `NATIVE_SITE_ROOT_ACLS_VERIFIED 2`,
`POSIX_0700_ARCHIVE_PARENTS_VERIFIED N`,
`POTENTIAL_NATIVE_DELETE_GRANTS N` and
`DSM_SMB_EFFECTIVE_RENAME_NOT_TESTED`. Neither a successful static ACL
audit nor POSIX 0700 proves effective SMB rename/delete prevention.

**Next safe operator acceptance:** Pull the feature branch to the isolated
worktree; run the complete offline `test_paperless_*.py` suite and
`audit-paperless-synology-archive-entry-protection.yml --syntax-check`.
Only after those pass, rerun the same read-only live audit. If the auditor
finds a different Linux-mode message, site-root mode, ACL or risky grant,
it must remain fail-closed; do not modify NAS ACLs or repeat commits.
No additional PDF move, automatic purge or `main` merge is authorized
by this change.

### 2026-10-17 corrective patch before live acceptance

The first local acceptance run after adding the Linux-mode exception
**failed**, with `732` synthetic tests, one failure in
`test_exact_native_linux_mode_requires_rc_255_and_empty_stderr`,
and an Ansible YAML parser error in the `POSIX_0700_ARCHIVE_PARENTS_VERIFIED`
assertion. The errors were introduced by overescaped literal backslashes
in the Python regular expression and by a truncated YAML expression.
**No live DSM ACL probe was attempted from that failed acceptance.**

Both defects are fixed in the PR branch: the regex now matches the exact
observed native tool output, and the POSIX summary assertion is a
complete, correctly quoted YAML string with one `fail_msg`.
An additional test uses `yaml.safe_load` to detect invalid playbook
syntax and requires the complete POSIX counter assertion. A local isolated
regex sanity check confirmed matching the exact Linux-mode example and
rejecting appended ACL content; this is **not** a production acceptance.
Expected complete Paperless suite count is now **733**, pending operator
verification on `bp-controller`.

Do not rerun the live ACL audit until all 733 tests and Ansible
`--syntax-check` pass. Archive moves, purge and promotion to
`main` remain unauthorized.

### 2026-10-17 first successful full protected archive DSM/POSIX ACL audit

Operator's full live execution of
`ansible/playbooks/audit-paperless-synology-archive-entry-protection.yml`
completed after the fixed Linux-mode parser and YAML acceptance
(`733` offline Paperless tests passed; playbook syntax check passed):

```text
AUDITED_ACTIVE_ARCHIVE_PARENT homes SITE_ROOT ACE_COUNT 3
AUDITED_ACTIVE_ARCHIVE_PARENT homes PROTECTED_ROOT POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT homes PROTECTED_INTERMEDIATE POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT homes PROTECTED_SCOPE POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT homes PROTECTED_SCOPE POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT paperless-scan SITE_ROOT ACE_COUNT 4
AUDITED_ACTIVE_ARCHIVE_PARENT paperless-scan PROTECTED_ROOT POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT paperless-scan PROTECTED_SCOPE POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT paperless-scan PROTECTED_SCOPE POSIX_0700_LINUX_MODE
AUDITED_ACTIVE_ARCHIVE_PARENT paperless-scan ARCHIVE_MONTH POSIX_0700_LINUX_MODE
NATIVE_SITE_ROOT_ACLS_VERIFIED 2
POSIX_0700_ARCHIVE_PARENTS_VERIFIED 8
ACTIVE_PROTECTED_ARCHIVE_PARENTS_AUDITED 10
POTENTIAL_NATIVE_DELETE_GRANTS 0
ARCHIVE_ENTRY_PROTECTION_NEEDS_EFFECTIVE_TEST
DSM_SMB_EFFECTIVE_RENAME_NOT_TESTED
ARCHIVE_COMMIT_NOT_AUTHORIZED
NO_FILES_CHANGED
```

Ansible: `localhost ok=4 changed=0 unreachable=0 failed=0 skipped=0`.
Native DSM ACEs were parsed at both site roots; each of the eight
protected inner archive directories, including the existing group
archive month directory, was verified as owned by `paperless-sync`,
POSIX mode `0700` and reporting the narrowly permitted native
`It's Linux mode` response. No dangerous nonadministrator native
delete grants were detected under the implemented static classification.

**This is only a successful static ACL/POSIX audit.** It does not
prove nonadministrative SMB sessions cannot rename/delete the protected
archive directory entry or read archive PDFs. Effective Samba/DSM
negative tests, isolated original recovery and independent off-NAS
backup+restore evidence remain outstanding. Successful completion
does not enable any additional original relocation, batch operation,
expiry/purge or merging Paperless into `main`.

The last independent archive lifecycle count prior to this audit was
`NAS_SENT_VERIFIED 21`, `NAS_ARCHIVED_VERIFIED 1`,
`NAS_CURRENT_ORIGINALS_VERIFIED 22`,
`PAPERLESS_LIVE_IMPORTED 22`, and exactly two documented user
deletions. This ACL-only run did not independently recalculate
those lifecycle counts; retain that evidence as a separate audit.


## 2026-10-17 isolated read-only recovery canary implementation (acceptance pending)

The 10-directory native DSM/POSIX static protection audit passed with
`NATIVE_SITE_ROOT_ACLS_VERIFIED 2`,
`POSIX_0700_ARCHIVE_PARENTS_VERIFIED 8` and
`POTENTIAL_NATIVE_DELETE_GRANTS 0`. It does not prove actual SMB rename
denial or independent off-NAS backup recovery.

A new separate read-only recovery playbook,
`ansible/playbooks/verify-paperless-one-group-isolated-recovery.yml`,
is intentionally pinned to the **sole already archived canary**
`Familie/Bergen-Platform-fuer-Dummies.pdf` (Paperless document 8). It:
(1) runs the existing full independent import/archived-journal lifecycle audit
quietly and requires **exactly 21 current SENT, one ARCHIVED,
22 live imported, and exactly two historical user deletions**;
(2) calls a restricted `paperless-sync` NAS stream program over SSH
via source-on-stdin; that program validates the protected root, both
canonical archived journal events, exactly the reviewed sender receipt,
the original source's absence, device/inode/size/mtime/ctime, full original
SHA-256 and PDF header/footer under `sync.lock`, and streams only
that PDF's bytes with bounded metadata; (3) copies those bytes to
**`bp-controller` `/dev/shm` tmpfs**, privately owned in a temporary
0700 directory, creates the disposable PDF with `O_EXCL|O_NOFOLLOW`
and mode `0600`, validates framing, SHA-256 and PDF structure, reopens
and rehashes the isolated copy, and removes it on scope exit;
(4) runs the same full lifecycle audit a second time, requiring the
original 21+1 counts and Paperless live/deletion evidence unchanged.
The NAS-side tool performs **no NAS writes at all**. It does not
create/delete archive entries, update receipts, create gates, invoke a
purge, or reimport any document. All private file bytes, names and raw
receipts remain hidden from Ansible's public output. A process crash
on `bp-controller` may leave a restricted tmpfs copy until reboot;
inspect and remove it under explicit controlled recovery if needed.

Implementation files:
`ansible/files/paperless/readonly_archive_recovery_stream.py`,
`ansible/files/paperless/verify_isolated_archive_recovery.py`,
and `tests/test_paperless_isolated_archive_recovery.py`.
The synthetic suite covers exact binary framing, size/hash/PDF corruption,
tmpfs copy protection, complete archived-journal binding, inode changes,
untrusted journal modifications and both read-only lifecycle imports.
No stage or activation step is needed. The staged NAS archive worker remains
unchanged and release gates remain absent.

**Acceptance pending on bp-controller:** Fast-forward the PR branch and run
the full `test_paperless_*.py` suite; syntax-check the new Ansible playbook.
Only after all tests/syntax pass, execute it with the normal local inventory,
Vault and Synology ignored variables. Passing isolated NAS-read/copy recovery
does **not** demonstrate restore from a separately stored backup or effective
nonadministrator SMB rename/delete denial. Those are subsequent independent
release gates for Paperless `main` promotion and any irreversible expiry.


## 2026-10-17 isolated canary recovery accepted

The operator executed
`ansible/playbooks/verify-paperless-one-group-isolated-recovery.yml`.
The live NAS+Paperless lifecycle was independently reconciled both before
and after the controller-side volatile-memory copy test. Reported terminal
proof:

```text
ISOLATED_GROUP_ARCHIVE_RESTORE_VERIFIED
POST_RESTORE_LIFECYCLE_RECONCILED
VOLATILE_SCRATCH_REMOVED
ARCHIVE_PURGE_NOT_AUTHORIZED
localhost ok=6 changed=0 unreachable=0 failed=0 skipped=0
venombox  ok=36 changed=0 unreachable=0 failed=0 skipped=2
```

The recovery stream selected only the already archived
`Familie/Bergen-Platform-fuer-Dummies.pdf` (Paperless document 8),
validated its protected NAS journal/source/receipt/size/inode/SHA/PDF
and produced an isolated mode-0600 `/dev/shm` copy on `bp-controller`.
The copy was rehashed and removed. The NAS journal/archive and the
22 live Paperless imports (21 source originals plus one ARCHIVED)
remain unchanged, and exactly two deliberate user deletions remain
reconciled. **This is a valid archived-original recovery exercise, but
not yet an independent external backup restore.** No live expiry or
purge authorization follows from it.

### Subsequent no-write SMB2 effective permission probe (development)

The feature branch now contains
`ansible/files/paperless/probe_synology_smb_delete_access.py` and
`tests/test_paperless_smb_delete_intent.py`. Using an explicitly
designated nonadministrative DSM SMB identity, the utility requests
**only SMB2 FILE_OPEN handles** (no create-on-missing, write, rename,
set-info, or delete-on-close). It tests:

- `DELETE` desired access to the existing
  `.bergen-paperless-archive` directory entry at a verified site-root
  share;
- `FILE_DELETE_CHILD` desired access at that site's share root;
- directory-list access to the protected archive root.

A success in **any** dangerous request fails the negative-access gate;
only the exact `STATUS_ACCESS_DENIED` error counts as denied.
Unknown SMB errors, incorrect share mapping, authentication failures,
unreachable shares, or ambiguous credentials are INCONCLUSIVE and
**never considered a passed protection test**. It requires the operator
to confirm that each target SMB share maps directly to
`/volume1/homes` or `/volume1/paperless-scan` and that the user
is actually nonadministrative, before relying on results. SMB password
is entered interactively (not in Ansible or command history).
Each passed run is evidence for **one authenticated identity and one
exposed share** only; broader identities, non-SMB protocols and a
controlled disposable rename/delete test are still separate checks.

The probe requires the optional Python `smbprotocol` package in
the operator's local virtual environment; the optional dependency is
not installed or invoked by the PR itself. Run synthetic tests first.
**Do not run any mutating SMB commands on actual protected archives**.
No automatic NAS authorization, ACL edits, archive move or purge
is part of the probe.

Further mandatory release gates: independently verified recoverable
backup of the post-canary Paperless + NAS protected archive and
journals (the 2026-10-15 vzdump precedes the canary); effective
permissions for all relevant private/group identities, and deliberate
separate approval of any expiring-purge implementation. PR #81 remains
a draft until all required criteria are proven.


### 2026-10-17 SMB2 static share-to-archive-root preflight

After the isolated archived PDF restore accepted and the first 748
offline Paperless tests succeeded, a strict **read-only share mapping**
audit was added before any SMB2 authorization probe:
`ansible/playbooks/audit-paperless-synology-smb-share-mapping.yml`,
`ansible/files/paperless/audit_synology_smb_share_mapping.py`,
`tests/test_paperless_smb_share_mapping.py`.

Under existing NAS root SSH transport the audit runs **only**
`synoshare --get homes` and `synoshare --get paperless-scan`, parses a
single exact Path field from each, and insists on
`/volume1/homes` and `/volume1/paperless-scan`, respectively.
It separately checks that both real paths are root-owned directory
site roots, never edits any DSM share, prints no private raw
`synoshare` output and fails closed for unrecognized share output.
It also read-only reports whether the optional local Python
`smbprotocol` module is installed. The mapping preflight only
verifies DSM's configured share path, **not** a logged-in user's
effective SMB home redirection/authorization.

After the new synthetic Paperless suite and Ansible syntax check
pass on `bp-controller`, run the mapping preflight read-only with
the same private ignored inventory and vault files. An acceptance
requires exactly:
`NAS_SMB_SHARE_REAL_ROOT_VERIFIED homes`,
`NAS_SMB_SHARE_REAL_ROOT_VERIFIED paperless-scan`,
`NAS_SMB_SHARE_MAPPING_VERIFIED 2`,
`SMB_NEGATIVE_RIGHTS_NOT_TESTED`, and `NO_FILES_CHANGED`.
Do not treat the mapping alone as proof of delete denial.
A real SMB identity must be explicitly approved as a normal
nonadministrator account; credentials must never enter Git or Ansible.
The initial `smbprotocol` implementation must first be reviewed for
the effective SMB topology and dependency; it is not automatically run
by mapping or any existing playbook.

Other gates still missing: actual negative effective SMB access (one
user is not universal proof), independent post-canary NAS+LXC
backup/restore, and any later destructive expiry/purge. There is
no new archive move, merge or purge authorization.


### 2026-10-17 real Synology SMB share-root preflight accepted

Operator confirmed `754/754` Paperless synthetic tests, successful
`audit-paperless-synology-smb-share-mapping.yml --syntax-check` and
read-only DSM SMB mapping live audit with
`localhost ok=6 changed=0 failed=0`. The exact NAS share mapping
was accepted for `homes` and `paperless-scan`, `NO_FILES_CHANGED`.
The optional dependency check reported `SMBPROTOCOL_NOT_INSTALLED`.
This is a **mapping-only** acceptance, NOT any SMB identity's deletion
rights evidence.

The low-level no-write SMB2 probe was then hardened before first use:
`Open.close()` sends real SMB CLOSE requests for successful FILE_OPEN
handles. Passing `False` would suppress sending the close and was
removed. Probe now refuses to prompt for a credential unless
`smbprotocol==1.17.0` is installed, the exact Python API version
reviewed for this script. PyPI published 1.17.0 on 2026-07-07 and
requires Python >=3.10. It supports SMB2/SMB3 and session encryption.
Seven offline SMB-specific tests now cover close, encryption,
dependency version gates and no-mutating-method invariants; all are
**pending operator verification** as part of full Paperless suite.

To install only in the activated `bp-controller` `.venv` after
local acceptance and explicit operator decision:
`python3 -m pip install 'smbprotocol==1.17.0'`.
Verify `python3 -m pip show smbprotocol` before any SMB credentials
are supplied. Do not place SMB passwords in shell history, Git,
Ansible extra-vars, process arguments or logs.

The standalone probe
`ansible/files/paperless/probe_synology_smb_delete_access.py`
must be run only with a confirmed nonadministrative **actual SMB
account** and the verified exact NAS SMB server and share. The
controller should not infer an identity, authorize privileged
accounts, or blindly try a home-redirection path.
Denied FILE_OPEN desired-access flags give negative evidence for one
SMB identity/share, but are NOT a physical rename/delete test. Unknown
results fail closed. No actual archive file or entry may be mutated
to test access. Future off-NAS backup/restore proof remains mandatory
for irreversible purge and main promotion.

