# Synology Paperless Inputs

Automated provisioning and validation of personal Paperless
scan input directories on Synology MountainCloud.

## Discovery

- LDAP homes: /volume1/homes/@LH-BERGEN.INTERN/61
- Eligible: members of Familie@bergen.intern
- Excluded: accounts outside this group
- Sync account: paperless-sync (local DSM user)

## Directory permissions

Each eligible LDAP user receives:

  <LDAP home>/Paperless

Synology ACLs grant:
- LDAP owner: full access
- paperless-sync: read/write/delete
- administrators: administrative access

No access is granted to other family members.

## Playbooks

preflight-synology-paperless.yml
  Read-only discovery and ACL inspection.

provision-synology-paperless.yml
  Idempotent directory provisioning.
  Requires synology_paperless_apply=true.

validate-synology-paperless.yml
  Real filesystem permission and isolation tests.
  Uses temporary synthetic files.
  Requires synology_paperless_validation_approved=true.

## Verified baseline

2026-10-12:
- Four eligible LDAP users
- Four personal Paperless directories
- Two excluded technical/administrative accounts
- Idempotency confirmed (changed=0)
- ACL runtime validation passed for all four users
- Real iPhone SMB scan verified
- Real PDF isolation verified against three other users

## Limitations

- New users require another provisioning run.
- Only existing DSM LDAP homes are discovered.
- Shared Eltern/Familie inputs are not provisioned here.
- No automatic Paperless document ingestion is enabled.
- Paperless document-level ACLs require separate validation.

## Safety

Never alter parent home ACLs.
Reject unexpected owners, symlinks and ACL deviations.
Run preflight before provisioning and validate afterward.
