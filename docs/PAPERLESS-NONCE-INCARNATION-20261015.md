# Paperless v2: durable nonce-bound scan incarnation (offline stage)

Status 2026-10-15: **OFFLINE LIBRARY ONLY.** Not installed on DSM and not
wired into the active `synology_scan_sync.py` sender, watcher, receiver,
archiver, quarantine, expiry or source deletion.

## Baseline preserved

The live read-only history audit confirmed **19 existing v1 SENT receipts**:
7 Privat/thomas, 0 Privat/nadja, 7 Eltern and 5 Familie. Zero PREPARED,
zero v2, zero unresolved. Every one of these remains untouched.

## Identity contract

A sender incarnation needs more than a hash of source bytes and NAS
`st_dev/st_ino/st_size/st_mtime_ns/st_ctime_ns`: Linux/DSM may reuse inodes
and timestamps, so two separate scan arrivals can have indistinguishable
file signatures.

The new `incarnation_id(scope, source, sha256, signature, nonce)`
uses a cryptographically random **128-bit nonce**, generated via
`secrets.token_hex(16)` under the existing exclusive `sync.lock`.
The proposed immutable PREPARED JSON includes
`"incarnation_nonce": "<32 lowercase hex>"`, the content digest and
the source signature. The nonce is bound into a domain-separated SHA-256
over the full record identity.

Both resulting file names visibly contain the same nonce:

```text
Receipt: v2-<32hex-nonce>-<64hex-hash>.prepared.json
SENT:    v2-<32hex-nonce>-<64hex-hash>.sent.json
rsync:   <scope>/nas-v2-<32hex-nonce>-<64hex-hash>.pdf
```

Changing nonce, file content, scope, basename or NAS signature changes
the identity. The old `version_id` helper is preserved solely for
**historical staged offline examples**; it is not used by the immutable
v2 store or the actual history reader.

## One-shot durable reservation

`reserve_prepared(directory, scope, source, sha256, signature)` is
an **offline library function**, not a CLI or product deployment. It:

1. Requires an existing, private 0700 directory and existing secure
   0600 sender lock. No directory or lock is created.
2. Locks the same `sync.lock` the old sender uses, then enumerates and
   validates recognized v1/v2 receipt events. It rejects orphaned,
   malformed or conflicting receipts.
3. Refuses a new nonce when *any* historical receipt uses the same scope
   and basename. This intentionally blocks reused original filenames
   until the separately verified archive/reuse lifecycle is designed.
4. Otherwise generates a new cryptographically random nonce, embeds it
   in PREPARED and target name, writes canonical JSON to a 0600 temporary
   file, fsyncs it, hard-links to the unique immutable final name
   without overwriting, and fsyncs the directory.
5. Returns only after persistence succeeds. After a crash following
   publication, a repeated call finds the historic PREPARED and **fails
   closed**: it does not create a new nonce or retransmit automatically.

SENT publication still requires the exact matching PREPARED and external
receiver evidence; the library does **not** verify this remote evidence.
The read-only NAS history audit now validates nonce-bound v2 filenames,
the PREPARED/SENT event pair and the legacy v1 format.

## Release blockers

Passing the offline tests alone is NOT permission to transfer or delete.
Before connecting the live NAS sender:

- Provide a secured, reviewed deployment and live journal-preservation
  and rollback plan. Preserve all 19 v1 receipts.
- Ensure no-overwrite remote destination publication and fresh digest
  verification; `rsync --ignore-existing` is not delivery proof.
- Bind each confirmed import to live Paperless document checksum, owner,
  group, effective permissions and protected user-deletion decisions.
- Implement crash-safe cross-subvolume private quarantine copy,
  checksummed receipt and source unlink only after durable proof;
  test all interruption points, including privacy regressions.
- Independently implement 30-day quarantine expiry, fresh backup-health
  gate, recovery drills and a complete approved end-to-end test.

No production sender change, automatic retry, archive, source deletion,
30-day purge or merge to `main` is authorized.

## Tests on bp-controller

In a checkout of `feat/paperless-incarnation-nonce-persistence-20261015`:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_incarnation_persistence.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_receipt_v2_store.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_receipt_history_audit.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_receipt_v2_transfer_contract.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_synology_receipt_versions.py' -v
```

Tests use isolated temporary directories and do not access DSM.
