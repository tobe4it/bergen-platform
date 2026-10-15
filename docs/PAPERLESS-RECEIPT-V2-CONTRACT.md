# Paperless v2 sender receipt and rsync name contract (offline stage)

Status: **DESIGN AND OFFLINE POLICY ONLY**, 2026-10-15. No deployment,
sender change, automatic NAS archival, source unlink, retention purge,
or promotion to `main` is authorized by this branch.

## Existing behavior and risk

The running NAS sender (`synology_scan_sync.py`) keeps one legacy receipt per
`SHA256(scope + NUL + original basename)`, with statuses `PREPARED` or
`SENT`. Its receiver filename is `<safe-stem>--nas-<content-sha256>.pdf`.
`rsync --ignore-existing` can return success for a preexisting target;
the sender therefore requires the specific newly-created transfer marker.
A crash after transfer and before SENT must remain subject to manual
reconciliation, never blind retransmission.

Two distinct files with the same original basename and identical bytes
would generate the same **legacy** receiver filename, even if their NAS
inode, timestamps and file incarnation differ. Naming only the journal v2
is insufficient; the destination must also change.

## Staged pure functions

`ansible/files/paperless/synology_receipt_versions.py` now proposes:

- `version_id(scope, basename, sha256, signature)`:
  `v2-<sha256(canonical versioned payload)>`.
- `receipt_filename(...)`: `v2-<id>.json`.
- `receiver_filename(...)`: `nas-v2-<id>.pdf`.
- `receiver_destination(...)`: `<scope>/nas-v2-<id>.pdf`.
- `classify_existing(...)`: rejects PREPARED, unknown, duplicated or
  inconsistent historical versions, and blocks reused names in the
  absence of an independently verified archival lifecycle.
- `preview_transfer(..., history_complete=True)`: produces only a JSON-
  serializable proposal tagged `preview_only=true`, with
  `archive_authorization=false` and `receiver_path_proof=NOT_CHECKED`.

The identifier binds all four logical fields: scope, original PDF basename,
content SHA-256 and the NAS file signature
(`st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns`). The receiver basename
does not expose the original filename. Historical v1 keys remain unchanged.
All currently used scopes remain logically isolated.

The preview cannot prove the caller discovered every historical receipt.
The argument `history_complete=True` is an assertion, **not** an independent
attestation. No production caller is wired to this API.

## Unresolved safety gates BEFORE live sender integration

1. Enumerate all v1/v2 receipts securely as the restricted user while
   holding the sender lock, verifying ownership, mode, symlink/hardlink
   exclusion and integrity. Do not assume an empty history when discovery
   fails or is incomplete. Preserve all 17 current SENT records.
2. Define durable per-incarnation creation and anti-replay metadata so an
   inode/timestamp combination reused after a filesystem lifecycle cannot
   silently alias an older version. The current signature-derived v2 hash
   alone does **not** prove perpetual uniqueness (inodes may be reused).
3. Define append-only, no-overwrite PREPARED/SENT publication with
   fsync and crash reconciliation, preserving v1 records. Validate that
   receiver destination does not already exist; never rely on
   `rsync --ignore-existing` to attest success.
4. Ensure the existing LXC bridge, live Paperless import proof, reconciliation
   exporter and archive evidence matcher accept the new receiver basename.
   Identical-content duplicate imports require a separate explicit policy;
   the changed filename does not force Paperless to import duplicates.
5. Obtain durable live IMPORTED proof with owner/group/effective ACLs,
   protect intentional DELETED_BY_USER journals, and implement
   checksum-verified cross-subvolume quarantine copy with recoverable
   receipts **before** removing the NAS original.
6. Add crash-injection, concurrent sender/archiver, filename reuse,
   receiver collision, hardlink/symlink and negative privacy tests; perform
   separate approved NAS end-to-end tests. Retention purge requires its own
   backup-health gate and 30-day quarantine rule.

The historical cross-device audit is still expected to print
`ARCHIVE_PREFLIGHT_BLOCKED`. This must not be overridden by passing the
offline v2 tests. `main` remains blocked until the complete import/archive/
source removal/purge process passes live safety and recovery tests.

## Offline verification on bp-controller

In a checkout of the **v2 branch**:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_synology_receipt_versions.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_receipt_v2_transfer_contract.py' -v
```

Neither command connects to DSM, reads private receipts, sends files, or
performs a deployment. The active sender and Synology installer are untouched.
