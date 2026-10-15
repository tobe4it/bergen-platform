# Paperless v2 – independent receiver-side file proof

Status: **READ-ONLY DEVELOPMENT ONLY**, 2026-10-15. No v2 files are
transferred by these changes, and the active Synology sender is unchanged.

## Why it is necessary

The NAS sender currently treats a specific rsync newly-created-file
record as a transfer signal. A successful rsync process exit can also
result from `--ignore-existing`; it does **not** prove that the remote
file matches the sender's original bytes. Meanwhile the Paperless
ingest bridge consumes an independent staging directory in LXC 126.

Proposed v2 policy requires independent receiver-side verification
**in addition to**, not in place of, an authenticated new-file rsync
transfer marker. The receiver's read-only check confirms only the file
that exists at the instant of inspection. It cannot prove fresh creation
or future continued existence, and it does not prove Paperless ingestion.

## New implementation

`ansible/files/paperless/verify_receiver_v2_staging.py` is a
standalone Python script streamed through `pct exec`, never
installed as a service. It checks:

- Exact path under `/srv/bergen-paperless/ingest-staging`; only
  `Privat/thomas`, `Privat/nadja`, `Eltern`, `Familie`.
- Exact nonce-bound receiver filename
  `nas-v2-<32hex-nonce>-<64hex-hash>.pdf`, from the immutable v2
  PREPARED journal; arbitrary paths and basenames rejected.
- Restricted `paperless-ingest` execution identity in guest.
- Root-owned 0750 staging/Privat directories, restricted-user-owned
  0700 scope directory and regular 0600 file with exactly one hard link.
- No-follow directory and file descriptors; unchanged owner, mode,
  inode, size, timestamps and link count across hashing and path recheck.
- Full streaming SHA-256, exact expected size and PDF header/end marker.

On success prints `RECEIVER_SHA256 <digest>`,
`RECEIVER_BYTES <size>`, `RECEIVER_POINT_IN_TIME_VERIFIED`,
`NEW_FILE_NOT_ATTESTED`, `PAPERLESS_IMPORT_NOT_ATTESTED`,
`SENT_NOT_AUTHORIZED`, `SOURCE_DELETE_NOT_AUTHORIZED`
and `NO_FILES_CHANGED`. Failures do not disclose document contents.

`ansible/playbooks/audit-paperless-v2-receiver.yml` runs it read-only
as `paperless-ingest` via Proxmox `venombox` and validates the LXC
identity and status first. **It requires exact expected parameters**
to prevent discovery of arbitrary receiver files. It does not create
files or publish any SENT event.

## Testing – safe now

In a checkout of this development branch on `bp-controller`:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_v2_receiver_readonly.py' -v
ansible-playbook \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-v2-receiver.yml \
  --syntax-check
```

The playbook's syntax check does not execute its live assertions. The
**live** playbook must not be executed until there is a separately
approved v2 test transfer and authenticated source PREPARED evidence
giving the exact relative destination, size and SHA-256. Merely
supplying arbitrary parameters is not a production release gate.

## Blocking work

For future automated `SENT`, a reviewed sender integration must
correlate the durable nonce-bound PREPARED event, rsync's strict
new-file marker and this independently executed receiver verifier.
It must handle a successful transfer followed by a crash before
SENT without retransmission or overwriting. A receiver digest proof
must never be treated as proof that the file was newly transferred.

Before source deletion or promotion to `main`, verify durable
Paperless IMPORTED ID/checksum/ACL evidence, intentional user-deletion
decisions, crash-safe cross-subvolume private quarantine copy,
retention and successful backup/restore tests.

All 19 historical v1 sender receipts remain intact, and no NAS,
LXC or scan files are modified by this PR.
