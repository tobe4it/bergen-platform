# Bergen Paperless: staged Synology iPhone scans and ASN labels

Status (2026-10-13): **the four personal and both shared Synology scan inputs are provisioned**. The Paperless-LXC is not yet connected to them, and ingestion remains disabled. Do not confuse provisioned Synology directories with a verified SMB mapping or document ACLs.

## Access model (not a tagging convention)

* Each person has a **personal** input on the Synology. Its trusted path
  maps to that exact non-superuser Paperless account (e.g. `Privat/benutzer`).
* Two shared inputs will map to the exact Paperless/OIDC groups `Eltern@bergen.intern` and `Familie@bergen.intern`.
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

## Synology NAS preparation (2026-10-12/13)

- Personal Paperless scan directories provisioned for Thomas, Nadja, Nils and Linda.
- LDAP group `Familie@bergen.intern` determines eligible personal inputs.
- LDAP administrator and IoT service accounts are excluded.
- Local DSM service account `paperless-sync` has no administrator privileges.
- Synology ACLs grant access to the owner, `paperless-sync` and administrators.
- Cross-user isolation and inherited file permissions verified successfully.
- Ansible preflight, provisioning and runtime validation passed.
- Second provisioning run confirmed idempotency (`changed=0`).
- Real iPhone SMB scan successfully saved and read by `paperless-sync`.
- Real PDF access denied to all three other tested family users.
- Shared `Eltern` and `Familie` inputs have also been provisioned, per the current operator confirmation. Their Samba share mapping and the current access restrictions must be separately confirmed from the Paperless LXC before any importer is enabled.
- The home-directory provisioner identifies personal inputs under `/volume1/homes/@LH-BERGEN.INTERN/61/<LDAP-home>/Paperless`; reported shared inputs are under `/volume1/paperless-scan/{Eltern,Familie}`. These are filesystem locations *on the Synology*, not SMB share names. Use only independently verified Samba share names when building the read-only mapping.
- The parent accounts `thomas` and `nadja` have tested OIDC membership in `Familie@bergen.intern` and `Eltern@bergen.intern`. Children and group-removal-on-relogin remain untested.
- The `Familie@bergen.intern` group has only `documents.view_uisettings`; no document ACLs are configured.
- Automatic provisioning schedule and Paperless importer are not enabled.
- Paperless document-level ownership and ACL workflows remain unverified.

## Remaining Paperless ingestion workflow

1. Existing iPhone Files -> SMB inputs stay on the Synology. Verify the network path from the Paperless LXC with `ansible/playbooks/preflight-paperless-synology-smb.yml`, and independently identify the exact SMB share paths. Do **not** treat a DSM filesystem path under `/volume1/` as a UNC path.
2. Use the existing, restricted DSM service account `paperless-sync` for a separately reviewed **read-only, authenticated** SMB test limited to the six allowlisted inputs. Do not place passwords in shell arguments, logs, the repository or general application environment. The future importer must verify regular files, permitted types, nonescaping paths, complete uploads, deduplication and a valid owner/group target.
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
**Attention:** The existing validator still accepts logical short labels `Eltern` and `Familie`, but effective Paperless group names now have the LDAP suffix `@bergen.intern`. Update that validator and associated tests before enabling live group routing.
It does not contact Synology or Paperless, check mount points, verify DSM ACLs,
provision Paperless users/groups, or enable any import.

## Read-only SMB connectivity preflight

The playbook `ansible/playbooks/preflight-paperless-synology-smb.yml` checks only whether TCP/445 on the internal SDS address is reachable from the Paperless LXC, whether `smbclient` and `mount.cifs` are already available and how many existing CIFS mounts the LXC reports. It **does not authenticate**, enumerate remote shares, mount, install packages, open PDFs, change services or copy files. It has no credential input.

```bash
cd ~/bergen-platform
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/preflight-paperless-synology-smb.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e synology_paperless_smb_host=192.168.2.145
```

After a successful network preflight, the next gate is a separately approved restricted `paperless-sync` credential-based SMB listing **without mounting** of each pre-existing input and a negative access test. We do not enable a NAS-to-Paperless import until the corresponding Paperless owner/ACL workflow is verified fail-closed.

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
