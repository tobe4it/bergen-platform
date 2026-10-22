# CT826: Offline-restore design – review only

Status: 2026-10-22. **Not approved, not executed.** No CT826 was created.
This is a security and operations design for an isolated Paperless/PG
metadata-ACL integration test, not a production installation runbook.

## Verified evidence

- Source: existing, unprivileged CT126 (Paperless), configured
  rootfs 32 GiB and backed-up mp0 100 GiB.
- Storage `local-zfs`: 1776 GiB free at inventory time;
  capacity planning requirement: 198 GiB.
- Candidate VMID **826** was free **at that point only**.
- Two CT126 NFS backups were recent. The chosen latest archive
  size was 1748 MiB, SHA256:
  `7f0ad64c2c7bc3bdca53be5766fbabc62feadd74025e811e52712e78b8bee24f`.
- Complete Zstandard stream and TAR directory integrity checks passed.
  No successful restore or PostgreSQL recovery has been proven.
- Archived CT configuration has exactly two raw LXC overrides:
  one cgroup device entry and one mount entry. The exact safe
  in-memory matcher identified the conventional **FUSE** pair:
  `c 10:229 rwm` and a bind of `/dev/fuse`.
- Most recent live audit deliberately blocked with
  `ARCHIVED_LXC_OVERRIDE_PRESENT`. This result is **correct**.
  Do not change the archive validator to accept low-level LXC rules
  merely because they match a known FUSE pattern.
- No integration runner, timer activation or isolated clone has occurred.

## Proxmox restore semantics – crucial distinction

Upstream documentation:
- https://github.com/proxmox/pve-docs/blob/master/pct.adoc
- https://github.com/proxmox/pve-docs/blob/master/generated/pct.1-synopsis.adoc

An advanced `pct restore` with explicit `--rootfs` and `--mp0`
**only overrides the backed-up mount-point configuration**.
It does **not** guarantee that `net0`, `onboot` or arbitrary low-level
`lxc.*` settings are removed. No one may interpret advanced mode as
"clean configuration" or "offline isolated". A normally networked
source is therefore unsafe to boot immediately after restore.

The interface from the archive must not be brought up, even briefly.
Isolating with a dummy gateway or a firewall rule is not equivalent
to a guest configured with **no network interfaces**.

## Required independent approval before any writes

Approve only after recording all of the following in a new reviewed
commit (the currently verified commit and hash are not a write
approval):

1. Confirm current VMID 826 absence cluster-wide and absence of
   dangling disks/datasets named for 826. Stop if any collision.
2. Rehash and pin **the same** verified backup file. Stop if a newer
   backup is auto-selected, an archive is replaced, a symlink appears,
   or an archived source configuration differs.
3. Check live `pct help restore` on this Proxmox version for the
   exact syntax of `--rootfs`, `--mp0`, `--onboot`, `--start`,
   `--unprivileged`, and optional hostname override.
4. Explicitly approve the new guest name (distinct from
   `bergen-paperless`), storage `local-zfs`, unprivileged mode,
   rootfs 32 GiB, data mp0 100 GiB at
   `/srv/bergen-paperless`, no bind mounts, no FUSE passthrough,
   no host USB/GPU device paths, no host LDAP/NFS mounts.
5. Design two discrete execution phases:
   **A. Restore WITHOUT BOOT**; explicit `onboot=0`, `start=0`,
   hard stop on task failure. **B. Before first boot, remove and
   independently verify absent every `net[0-9]+` and every
   `lxc.*` setting** in restored config.
   This is an intentional *two-phase* restore to accommodate inherited
   source config. Do not bundle a boot/start into the restore command.
6. Block concurrent actors: no other automation can boot an incomplete
   clone. Audit restored config before and after guest property edits.
   No boot approval while any live NIC, raw LXC override, hookscript,
   external mount, or onboot setting remains.
7. Pre-existing OS/application timers, SMTP, LDAP/SSO, webhook,
   document ingestion and consumer services are untrusted until
   disabled or isolated. If the clone is eventually booted, it must
   have NO network interface and no off-host mount access.
8. After the clone is entirely offline and PostgreSQL startup and
   document privacy checks are separately approved, construct
   **synthetic test metadata in the clone only**. Require successful
   grant, revocation, no-op/idempotence, transaction rollback and
   concurrent ACL drift checks before a production timer review.
9. Post-integration clean-up requires a separate explicit deletion
   approval. Never delete the production CT126 or any real backups.

## Explicit non-goals of this design

- No `pct restore`, `pct set`, `pct start`, `pvesm alloc`,
  dataset create or delete is executed.
- No production ACL, authentication, DB, networking or timers change.
- **No network isolation has been proven**; absence of a proposed
  interface in a paper plan is not a verified running-guest property.
- **No PostgreSQL integration has been proven**; pure policy tests
  are not substitutes for the actual Django/Guardian database state.

## Proposed next artifact

A separately reviewed Ansible restore-stage playbook should require
a known commit SHA, the archive SHA256, a separate restore approval
boolean, expected storage/volume values and exact VMID, and should
perform only Phase A. It must *never* automatically boot or turn on
the production timer. Follow it with an independently reviewed
post-restore configuration sanitization/verification playbook, again
with no boot. Then require a third approval to start the offline
fixture. Until all these gates exist and are tested, keep CT826 absent.
