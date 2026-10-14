# Paperless scan inbox lifecycle: verified import, NAS quarantine, expiry

Status: **design approved, implementation NOT deployed** (2026-10-14). The active
Synology sender and Paperless ingest pipeline remain copy-only. In particular,
no script or timer may delete or rename an original scan based solely on SENT.

## Objective

Keep the source Paperless scan folders flat and empty after *verified* import,
without inventing a permanent folder hierarchy on Synology. Paperless is the
authoritative searchable archive. The NAS holds a short-lived, private
recovery copy after acknowledgement, not a second organised document library.

Current enabled scopes: Privat/thomas, Privat/nadja, Eltern, Familie. Do not
enable any additional private scopes until the Paperless account, workflow
and ACL checks exist.

## Backup baseline (verified separately)

Proxmox guest 126 `bergen-paperless`: 32 GiB rootfs plus 100 GiB `mp0`
document volume with `backup=1`. Backup destination
`bergen-synology-backup` on Synology NFS. `vzdump` stop mode + zstd.
A full recovery into isolated test guest 901 was completed on 2026-10-12,
including PostgreSQL, Redis, Paperless and an OCR test document; the test
guest was subsequently removed. Additional protected archive created
2026-10-13. The systemd units `bergen-paperless-vzdump.service` and
`.timer` run at 03:00 Europe/Berlin. The 2026-10-14 run completed successfully
at 03:02:54, with rootfs and mp0 included and an archive present on the NFS
target. The executed retention was keep-daily=7, keep-weekly=4,
keep-monthly=12. Purge still needs a fresh backup-health check at the time
of each deletion, not just this historical evidence. A successful historical restore is not
proof that the unattended job continues to work.

## Fail-closed workflow

1. Synology sender detects a stable PDF and copies it through the existing
   restricted rsync receiver. It records SHA-256, sender source filename,
   scope, destination and signature in its private SENT journal.
2. Paperless LXC stages and imports the document. Its reconciliation journal
   records IMPORTED only after a live document-ID, checksum, owner, group,
   direct-permissions and active-user visibility verification.
3. A trusted controller workflow via **existing** access
   `bp-controller -> venombox -> pct exec 126` re-verifies the live Paperless
   document and emits a narrow acknowledgement containing the receiver-side
   destination name, SHA-256, document ID and bridge receipt identity.
   No new inbound NAS, Paperless or SSH connection is necessary.
4. Through the existing NAS administrative connection, a *short-lived* NAS
   archiver validates that acknowledgement against its own SENT receipt and
   verifies the original source is the *same* file with the *same* digest
   and signature. The archiver has a lock and durable journal. If any
   comparison fails, it must leave the original source in place.
5. After validated live import proof, the archive step atomically moves
   the original PDF from the monitored input into a private,
   non-watched quarantine owned by the restricted sync account within
   `state_parent/paperless-archive/<scope>/YYYY-MM/`. Private and shared
   scopes remain separated; no new read grants are created.
   The restricted `paperless-sync` account is intended to have **read and
   delete** rights on PDFs inside its permitted scan input directories:
   traversing/listing, reading, and removing successfully processed originals
   are necessary; creating/editing PDF content, changing ACLs or ownership,
   and access to other home content are not. Synology ACL permissions for
   unlink/rename depend on directory-level delete/delete-child rights.
   The current broad input ACE permits more than this target and must not
   be blindly replaced while production ingest is running.
   The quarantine directory and its scope/month subdirectories are owned by
   the configured `paperless-sync` account (group `users`) and use mode `0700`.
   Its application parent and code/config remain root:root `0755` / root-owned.
   The same account is authorised to move verified originals into this
   quarantine and to delete expired archived PDFs. Time-based deletion is
   enforced by the scheduled application logic, **not by the filesystem ACL**;
   thus compromise of the sync account can also cause early deletion. Run
   the expiry worker as `paperless-sync` with no elevation. Minimise its
   capabilities, keep durable audit receipts and verify periodic backups.
6. The NAS receipt remains durable, so the same scan cannot be resent merely
   because it has disappeared from the inbox. A crash after rename and before
   journal update must be recoverable by examining the quarantine target
   and its digest, never by blindly repeating a destructive rename.
7. Purge after >=30 full days in quarantine must be a **separate, disabled-by-
   default** operation. It must require a verified recent successful backup
   on the configured target (covering rootfs and mp0) and a healthy timer,
   must refuse ambiguous/missing evidence, and never touch inbox files.
   Once enabled, preview the exact purge candidates before the first deletion.

## Required sender-journal change for reused scanner filenames

The current NAS sender keys a receipt by `(scope, basename)` and refuses a
different signature at the same path with `MANUAL_REVIEW_SOURCE_CHANGED`.
Once quarantine empties an input directory, scanners may legitimately create
another file such as `Gescanntes Dokument.pdf`. **Do not deploy automatic
quarantine before changing this rule.** Introduce an append-only, per-version
receipt identity using an unambiguous, validated source fingerprint including
SHA-256; retain old SENT journal entries for backward compatibility. Refuse
ambiguous/prepared outcomes, never overwrite prior receipts, and add regression
tests for identical names across multiple successive imports, replay, modified
content and crash recovery.

Also verify the future archiver's month rollover provisioning and privacy
boundary: existing NAS scanner folders may have Synology-specific ACLs, while
the private sync-user-owned quarantine must not inherit an unintended shared ACL.
A new LDAP home requires per-home safe provision and explicit Paperless
workflow/ACL activation before its scope may be monitored.

## Threats/tests to cover before deployment

- Wrong owner/group or privacy ACL, missing active-user visibility, digest
  mismatch, missing or forged receipt, PREPARED/SUBMITTED/PENDING state.
- Replaced/edited source since SENT, symlinks, multiple hardlinks, invalid
  input path, directory traversal, unsafe file permissions, mount loss.
- Interrupted copy or rename, destination already exists, cross-device
  rename, repeated acknowledgement, partial receipt write.
- Unexpected Paperless downtime or failed daily backup: *do not purge*.
- New scans arriving while archiving: sender lock and journal invariants hold.
- Manual NAS recovery from quarantine remains possible for 30 days.

## Current status / deployment gate

On 2026-10-14 the live sender completed startup with `SYNC_END STARTUP rc=0`.
Nine Paperless documents (IDs 5-13) were imported; IDs 10-13 underwent a
fresh successful live ACL and SHA-256 audit. **No NAS archival or purge
mechanism is deployed yet.** Do not infer that this design document activates
it. Implement, test in dry-run and deploy the archive stage separately;
enable automatic expiry only after backup verification.
