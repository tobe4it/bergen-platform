# Paperless archive preflight and main promotion gate

Status, 2026-10-15: READ-ONLY ONLY. No archive worker, inbox deletion or
quarantine purge is enabled by this change. Paperless stays outside main
until the full import, archival and deletion lifecycle is proven.

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

## Mandatory criteria for merging Paperless into main

1. Every imported scan is reconciled with a live Paperless document ID,
   SHA-256, effective owner/group and visibility. Deliberately deleted
   Paperless documents are never implicitly reimported.
2. Filename reuse, successive identical names, rsync destination
   collisions and repeated/partial receipts have collision-free versioned
   identities with replay protection and exhaustive regression tests.
3. Private NAS quarantine receives a durable checksum-verified copy
   across subvolumes with a crash-recoverable journal and explicit
   verified-import acknowledgement. No cross-device atomic rename
   is assumed.
4. Only then may the still-identical scan original be removed from the
   inbox. Crash injection at every copy, publish, fsync, receipt and
   remove boundary must recover safely; mismatches must fail closed.
5. Quarantine is recoverable for at least 30 full days. A separate,
   explicitly approved expiry worker verifies fresh successful backup
   health at purge time, limits deletion to exact eligible archived
   files and fails closed on any ambiguity or outage.
6. Four configured privacy scopes pass negative effective DSM and
   Paperless ACL tests; operational backup/restore is independently
   checked. Live positive and negative end-to-end tests are approved.
7. Merge the Paperless feature stack (PR #60 or successor) into main
   only after these criteria pass. Read-only checks do not bypass them.

This historical two-journal verifier is intentionally pinned to
documents 15 and 26; it does not discover new journals and must not
serve as the future general backup gate for retention purges.
