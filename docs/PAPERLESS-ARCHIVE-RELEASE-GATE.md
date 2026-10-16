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
