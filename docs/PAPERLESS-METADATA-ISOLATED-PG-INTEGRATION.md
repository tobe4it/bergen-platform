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


## Phase D.2: Exact archive fingerprint and read-only format validation

Proxmox restores a backed-up LXC configuration by default, including
interfaces and mounts unless options are explicitly overridden.
Therefore, a successful storage/VMID survey must **not** be treated as
permission to boot the restored Paperless guest. Official Proxmox pct
documentation explicitly distinguishes "simple" restore (which
restores backed up mount configuration) and "advanced" restore
(which discards/overrides it). Review both the source archive config
and the target no-NIC configuration before any boot.

The new \`audit-paperless-metadata-archive-integrity.yml\` scans only
the **most recent** valid NFS \`vzdump-lxc-126-*.tar.zst\` file,
never enumerates archive member filenames to the Ansible output,
streams a full SHA256 and performs Zstd decompression and tar header
listing checks without extraction.

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-metadata-auto"
  cd "$WT"
  test -z "$(git status --porcelain)"

  "$BASE/.venv/bin/python" -m unittest discover \\
    -s tests -p 'test_paperless_metadata_archive_integrity.py' -v

  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/audit-paperless-metadata-archive-integrity.yml \\
    --vault-id ai@prompt
)
\`\`\`

A validated run yields \`ARCHIVE_SHA256\` and the archived size.
Pin both during any later restore approval; never substitute the
filename or a newer backup silently. This is a **multi-pass NFS
read** and may generate noticeable IO. It causes no guest, database,
network or backup writes.

Even if Zstd/tar checks pass, restore compatibility, required metadata
or PostgreSQL startup/recovery remain unproven. At present, there is
no automatic restore or boot operation prepared/approved.


## Phase D.3: Verify exact pinned backed-up CT config (no write)

The last archive check on 22.10.2026 succeeded:
- size 1748 MiB
- SHA256
  \`7f0ad64c2c7bc3bdca53be5766fbabc62feadd74025e811e52712e78b8bee24f\`
- Zstandard PASSED; TAR directory scan PASSED.

Read-only audit: \`audit-paperless-metadata-pinned-restore-config.yml\`.
It verifies the full SHA256 **again**, asks Proxmox for the archive
volume path and its embedded \`pct.conf\` using the native
\`pvesm extractconfig\` command, validates archive unprivileged mode,
rootfs and backup-included mp0, checks for additional mounts, hooks and
LXC overrides, and emits **only sanitized categories**.

The archive is expected to contain a network interface because the
production source is networked. That network **must not be inherited
by a booted test clone**. Any later restore is a *separately approved*
write and must be followed by independent inspection that the clone
has zero net interfaces and onboot=0, then a separate boot gate.
Do not interpret an archived network setting as proof of offline
isolation.

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  cd "$HOME/bergen-platform-metadata-auto"
  test -z "$(git status --porcelain)"

  "$BASE/.venv/bin/python" -m unittest discover -s tests \\
    -p 'test_paperless_metadata_pinned_restore_config.py' -v

  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/audit-paperless-metadata-pinned-restore-config.yml \\
    --vault-id ai@prompt
)
\`\`\`

The expected status is \`PINNED_ARCHIVE_CONFIG_REVIEWED\`, with
\`RESTORE_PERFORMED=NO\`, \`NETWORK_ISOLATION_PROVEN=NO\` and
\`CLONE_CREATED=NO\`. If backup rotation creates a newer archive
before inspection, \`ARCHIVE_FINGERPRINT_DRIFT\` is **expected**;
do not silently repin. Independently validate the new archive and
explicitly approve a new fingerprint instead.

A later restore must not occur solely because this audit passed.
Proxmox restores stored CT properties by default; the network
inheritance issue must be handled before any guest startup.


## Phase D.4: Archived LXC override triage – still NO RESTORE

The 22.10.2026 read-only pinned archive audit reached
\`REASON=ARCHIVED_LXC_OVERRIDE_PRESENT\`. This is a refusal, not
evidence that the archive or its extra LXC configuration is safe.

Run the same pinned audit with the updated fixed-category diagnostic
only. It now emits \`LXC_OVERRIDE_COUNT\` and
\`LXC_OVERRIDE_CLASSES\` exclusively from a fixed list:
\`APPARMOR_OVERRIDE\`, \`CGROUP_DEVICE_OVERRIDE\`,
\`MOUNT_OVERRIDE\`, \`CAPABILITY_OVERRIDE\`,
\`SECCOMP_OVERRIDE\`, \`IDMAP_OVERRIDE\`,
\`NETWORK_OVERRIDE\`, \`HOST_HOOK_OVERRIDE\`,
\`ENVIRONMENT_OVERRIDE\`, \`OTHER_LXC_OVERRIDE\`.

Never output raw \`pct.conf\`, override keys or values, device rules,
paths, secret environment strings, network endpoints or bind mounts.
The audit must continue failing with \`STATUS=BLOCKED\` even when it
successfully classifies the existing override types. This intentional
failure prevents a premature restore or timer activation. Do not
allowlist any override for CT826 merely based on its category.
Review actual required LXC runtime functionality **privately** and
design a stripped no-network test configuration with a separate approval.


## Phase D.5: Exact FUSE-pattern recognition without copying device access

The archived CT126 configuration has been confirmed to contain exactly
two extra LXC settings classified only as one \`CGROUP_DEVICE_OVERRIDE\`
and one \`MOUNT_OVERRIDE\`. This is consistent with, but does not prove,
a FUSE host-device allowance.

A further **read-only** pinned-backup audit compares the *in-memory*
values to an exact narrow FUSE pattern: device rule
\`c 10:229 rwm\` and an LXC mount for \`/dev/fuse\` with explicitly
recognized bind and create-file options. No actual archive key/value
or host path is emitted. Only these fixed results appear:

- \`CGROUP_DEVICE_PROFILE=EXACT_FUSE_DEVICE_10_229\` or
  \`OTHER_OR_MISSING_CGROUP_RULE\`;
- \`MOUNT_ENTRY_PROFILE=EXACT_FUSE_DEVICE_BIND\` or
  \`OTHER_OR_MISSING_MOUNT_RULE\`;
- \`FUSE_PAIR_PROFILE=MATCHES_KNOWN_FUSE_PATTERN\` or
  \`NOT_PROVEN\`.

**A known FUSE pair does not authorize restore or passthrough.**
The inspection deliberately stays \`STATUS=BLOCKED\` and Ansible
\`failed=1,changed=0\`. The proposed test clone must omit inherited
raw LXC device and mount rules, and must have no NIC before first boot.
Whether PostgreSQL and Podman can run without FUSE requires a
separate isolated integration test; do not assume either way.

Proxmox documentation: normal restore reuses backed-up config;
advanced restore overrides rootfs/mpX. A safe no-network lifecycle
needs independently verified configuration before the test guest
can ever start.
