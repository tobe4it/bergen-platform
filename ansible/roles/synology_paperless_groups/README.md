# Synology shared Paperless scan directories (staged)

Scope: only `/volume1/paperless-scan/{Eltern,Familie}` and the explicitly
reviewed `Familie` ACE on `/volume1/paperless-scan`.

This feature is **not wired into the daily personal-input timer**.
Paperless ingestion remains disabled.

The review found `Familie@bergen.intern` inherited full access from the
share root, including `D` (delete child). Nils deleted an otherwise protected
temporary child directory. A separate test proved that a direct, non-inherited
group-folder ACL with *root* group rights limited to read/traverse prevents that.

Provisioning therefore has three separate explicit gates:

1. Read-only preflight:
   `ansible/playbooks/preflight-synology-paperless-groups.yml`
2. Review and apply the root-only ACL hardening, with
   `-e synology_paperless_root_harden_approved=true`:
   `ansible/playbooks/harden-synology-paperless-groups-root.yml`
3. Provision only two directories, with
   `-e synology_paperless_groups_apply=true`:
   `ansible/playbooks/provision-synology-paperless-groups.yml`
4. Runtime test of synthetic temporary files, with
   `-e synology_paperless_groups_validation_approved=true`:
   `ansible/playbooks/validate-synology-paperless-groups.yml`

Run all with `-i 'ldap.thebergens.net,' -u supervisor --become` and the
existing `~/bergen-platform/.venv/bin/ansible-playbook` executable.

The preflight accepts only the reviewed legacy root ACL or hardened root ACL,
including exactly four direct ACEs. The hardening step replaces exactly index
3 of the known legacy ACL. Unrecognized ACLs, symlinks, unexpected owners,
and unknown child ACLs fail closed. If child creation is interrupted, rerun
the read-only preflight to identify any partial state before retrying.

**Security boundaries:** Local filesystem checks do not prove the complete
SMB access policy; verify DSM share permissions and guest access separately.
The trusted `paperless-sync` principal retains full access to the shared
root. This is a deliberately explicit operational exception; further
least-privilege reduction requires separate design and testing.

Validate SMB access as normal users and a guest/unauthenticated session
before introducing real documents. Verify the downstream Paperless owner/
group ACL mapping and import quarantine independently. No timer or importer
switches are changed in this branch.
