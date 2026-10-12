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

## Automatic provisioning

Prepared systemd user units:

- systemd/user/bergen-paperless-autoprovision.service.example
- systemd/user/bergen-paperless-autoprovision.timer.example

The service executes under the Linux user ansible on bp-controller.

Schedule:
- Daily at 05:00 local time
- Up to 30 minutes randomized delay
- Persistent scheduling enabled

Runtime:
- Pinned runtime checkout: /home/ansible/bergen-platform-paperless-runtime
- Target: ldap.thebergens.net
- SSH identity: supervisor
- Remote privilege escalation: sudo

The provisioning playbook performs:
1. Read-only discovery and ACL preflight
2. Idempotent provisioning of missing inputs
3. Final ACL verification

Operational safeguards:
- No automatic Git pull
- No execution from feature worktrees
- No change to parent LDAP home ACLs
- No NAS-to-Paperless ingestion
- No periodic creation of synthetic validation files
- Journal logging through systemd

Deployment is disabled until the reviewed release is
available in the pinned Paperless runtime checkout.

After deployment, inspect with:
  systemctl --user status bergen-paperless-autoprovision.timer
  journalctl --user -u bergen-paperless-autoprovision.service
