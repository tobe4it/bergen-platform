# Bergen Paperless: staged Synology iPhone scans and ASN labels

Status: **design and offline preflight only; no NAS integration or ingestion
has been enabled**. This change builds on the separate Paperless backend draft
(PR #54), not on the Proxmox backup worktree.

## Access model (not a tagging convention)

* Each person has a **personal** input on the Synology. Its trusted path
  maps to that exact non-superuser Paperless account (e.g. `Privat/benutzer`).
* Two shared inputs map to the Paperless groups `Eltern` and `Familie`.
  Group permission is **read**, not an implication that all group members
  may change or delete the document.
* The Paperless `admin` account is a separate break-glass superuser and
  is not a normal LDAP principal. An administrator can nevertheless access
  all documents; it is not constrained by document-level ACLs.
* LDAP/SSO identifies people and supplies group membership, but it does not
  identify the scanner's sender. The **verified NAS source directory** supplies
  the scan's intended owner or group.

An input with no valid mapping must be **quarantined before reaching
Paperless**. Never use `tags` as a replacement for object permissions.
In the currently deployed Paperless configuration, a document without an
owner can be visible to ordinary users. Consequently a path filter alone is
**not** a sufficient fail-closed guarantee.

## Proposed flow (not implemented by this change)

1. iPhone Files -> SMB -> an existing Synology folder with suitable DSM ACLs.
   First verify whether the three logical areas are shares, `homes` or
   subfolders; the example paths below are **not** validated site paths.
2. A future dedicated, restricted service account may read **only**
   explicitly allowlisted incoming folders. This service must verify a regular
   file, allowed type, safe real path (no symlink escape), stable completed
   upload, deduplication/idempotency, and an available destination.
3. A future staging importer sends each item to the matching local consume
   subdirectory. Unknown paths and principals are denied or quarantined.
   It must not delete originals until a correct Paperless document, ACL
   state and checksum have been verified. Document moves must be logged.
4. Paperless `Consumption Started` workflows use exact source/path
   matching to set **owner and ACLs**. These must be reviewed against the
   running 3.3.0 instance and tested with non-superuser identities.
5. Only after **end-to-end negative access tests** may recursive consumption
   and the actual file importer be separately proposed and enabled.

Do not mount the Synology as Paperless media/database storage: the archive
remains on the dedicated ZFS volume protected by Proxmox backups.

## Planning route allowlist

The checked-in example
`docs/examples/paperless.scan-ingest.example.yml` defines precisely
`source_path` (NAS staging location), `consume_subdir` (local target),
`scope` and `principal`. It is an example, not a live inventory.

To fill it in on the Ansible controller:

```bash
cd ~/bergen-platform
cp docs/examples/paperless.scan-ingest.example.yml \
  ansible/vars/paperless.scan-ingest.local.yml
chmod 600 ansible/vars/paperless.scan-ingest.local.yml
vim ansible/vars/paperless.scan-ingest.local.yml
python3 ansible/scripts/paperless_scan_map_preflight.py \
  ansible/vars/paperless.scan-ingest.local.yml
python3 -m unittest discover -s tests \
  -p 'test_paperless_scan_ingest.py' -v
```

This **offline** check rejects unknown scopes, duplicate/overlapping source
paths, duplicate targets, private-owner mismatches and unknown shared groups.
It does not contact Synology or Paperless, check mount points, verify DSM ACLs,
provision Paperless users/groups, or enable any import.

## ASN label support (prepared; off by default)

The Ansible Paperless role now accepts
`paperless_scan_asn_enabled: true`, which writes:

```ini
PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE=true
PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX=ASN
```

The switch defaults to `false`. Recursive consumption is explicitly kept
`false`; barcode document splitting is **not** enabled. This is suitable
for testing Avery L4731 QR/ASN labels independently of bulk-import routing.
The PR does not change the running service, enable a NAS mount or create
users, groups or workflows.

Only one global ASN sequence should be used for all personal/shared sources.
An ASN is an archive reference, not an authorization token.

## Separate live release gate

Before applying any scan ingestion, collect and review:

- Actual Synology share/subfolder paths and DSM permissions for each person,
  `Eltern`, and `Familie`.
- The exact LDAP/SSO usernames and actual mapped Paperless accounts and groups;
  verify they exist before private workflow assignment.
- The Paperless 3.3.0 workflow trigger filters and permission actions by
  read-only inspection; prove exclusive mapping before recursive scanning.
- Isolation tests as at least **two** different ordinary users:
  private-A is invisible to B, group-Eltern invisible to nonmembers,
  group-Familie visible only to members. Check negative access via API too.
- ASN QR recognition on an unimportant synthetic document and successful
  recovery of source file after an error; confirm filename-collision behavior.
- Audited retention, quarantine and no early delete, plus backup/restore.

**No real documents until all gates pass.** Keep LXC 126's existing
loopback-only backend, PostgreSQL/Redis and backup schedule unchanged.
