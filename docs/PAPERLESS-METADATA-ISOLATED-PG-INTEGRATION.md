# Phase D: Paperless metadata – isolated PostgreSQL integration

Status 2026-10-22: **no-write feasibility audit staged; no clone provisioned**.
Successful production provenance bootstrap and independent read-only audit
have established LEDGER=VALID, documents=60, users=3, tags=38, zero gaps,
zero managed provenance entries and 9 Thomas-private documents denied to Nadja.
Those results are a baseline, **not** evidence of tested grant-revoke cycles.

## Scope and isolation requirements

Before testing native Guardian writes, restore a reviewed CT126 backup to a
**separate unprivileged guest** with a unique unused Proxmox VMID and
independent storage. A CT restored from a real Paperless archive includes
sensitive data: do not attach it to the household LAN/DMZ, DNS, reverse
proxy, LDAP/OIDC, mail server, mounted Synology shares or Ollama. In
particular, protect against background workers, SSO connections, SMTP,
webhooks, consume dirs and cron being enabled by an imported configuration.

1. Read-only survey: correct existing source CT126, included Paperless
   data mount and an NFS backup younger than 48 hours.
2. *Separately approve* the exact VMID, isolation mechanism (no uplink,
   no host networking, no externally reachable service), storage location,
   capped resources, restore archive fingerprint, cleanup plan and
   controlled test user identities.
3. Restore into the isolated target **without starting application or
   background workers** and independently establish network isolation.
4. Audit the restored PostgreSQL baseline and ensure no client can reach
   production. Only then create synthetic test-only Tag, DocumentType and
   Correspondent fixtures in the clone.
5. Run the *actual* \`reconcile_metadata_with_provenance.py\` against the
   clone database under approved apply gates. Verify:
   - new Tag -> native family \`view_tag\` + one owned ledger entry;
   - new type/correspondent linked to a shared document -> only readers
     receive \`view_documenttype\`/\`view_correspondent\`;
   - no grant to a user without \`view_document\`;
   - repeated run creates no duplicate and reports zero changes;
   - after last visible link disappears, only ledger-owned grants revoke;
   - old manual grants remain, regardless of shared/private linkage;
   - transaction rollback after an injected postcondition failure;
   - concurrent metadata/document-ACL changes abort or retry safely;
   - full production privacy invariants unchanged.
6. Check no secrets/log contents leave the isolated fixture; stop, wipe
   and independently verify cleanup only after explicit approval.
7. Only after all tests pass: review separate
   \`activate-paperless-metadata-timer.yml\` approval and worker
   credentials/files/time/budget. Do not implicitly enable a timer.

## Read-only backup/isolation readiness on venombox

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-metadata-auto"
  cd "$WT"
  test -z "$(git status --porcelain)"

  "$BASE/.venv/bin/python" -m unittest discover -s tests \\
    -p 'test_paperless_metadata_isolated_test_readiness.py' -v

  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/audit-paperless-metadata-isolated-test-readiness.yml \\
    --vault-id ai@prompt
)
\`\`\`

Output is bounded to status, backup archive count/size and NO values
for clone creation, restore verification, network isolation and actual
PostgreSQL integration. Even if STATUS=BACKUP_READY_FOR_ISOLATED_RESTORE_REVIEW,
that alone proves **only a recent archive exists**. Archive integrity,
ability to restore, adequate independent ZFS space and safe network
isolation remain unproven.

**No production mutation, database fixture, timer installation or
network modification in this playbook.** There is deliberately no
automated pct restore or pct start command in this initial phase.


## Phase D.1: Read-only VMID and ZFS capacity design

Run the separately staged \`ansible/playbooks/audit-paperless-metadata-clone-plan.yml\`
only after the backup/readiness audit succeeds. It checks Proxmox
cluster-wide used VMIDs via the read-only cluster resource API,
prefers VMID **826** if free (else uses a free alternative 820–829),
and reads the existing \`local-zfs\` free space and configured
rootfs plus backed-up Paperless data-mount sizes. The minimum free
space for **planning** is 1.5 times configured source volume sizes,
with a 16 GiB floor. This is only conservative admission control,
not a promise of successful restore.

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  cd "$HOME/bergen-platform-metadata-auto"
  test -z "$(git status --porcelain)"

  "$BASE/.venv/bin/python" -m unittest discover -s tests \\
    -p 'test_paperless_metadata_clone_plan.py' -v

  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/audit-paperless-metadata-clone-plan.yml \\
    --vault-id ai@prompt
)
\`\`\`

**No test guest is created, no ID is reserved and no network
isolation is yet proven.** A VMID reported as free can be taken after
the audit. There is deliberately no restore command in this phase.
The isolated guest must be off-network from its first possible boot
and have no reachable LDAP/MX/Ollama/Synology connection.
