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
- Shared Eltern/Familie inputs are provisioned and reviewed via a separate role; the daily job audits them read-only.
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

The daily systemd oneshot executes two ordered Ansible playbooks:
1. Personal LDAP home Paperless inputs: read-only discovery, idempotent
   provisioning of missing inputs, final ACL verification.
2. Shared inputs: `audit-synology-paperless-groups.yml`, read-only.
   The audit requires `/volume1/paperless-scan` to be hardened and both
   `Eltern` and `Familie` to exist with exactly the reviewed direct ACLs.
   Deviations fail the service; there is **no automatic repair** of group ACLs.
   Periodic runtime probes with synthetic files are not performed.

Operational safeguards:
- No automatic Git pull
- No execution from feature worktrees
- No change to parent LDAP home ACLs
- No automatic shared-root ACL changes or group-directory creation
- No NAS-to-Paperless ingestion
- No periodic creation of synthetic validation files
- Journal logging through systemd

The systemd timer was previously activated with the personal-only service.
The group audit service change is staged until deliberately deployed and
tested on the pinned runtime checkout. Do not enable any new importer.

After deployment, inspect with:
  systemctl --user status bergen-paperless-autoprovision.timer
  journalctl --user -u bergen-paperless-autoprovision.service
