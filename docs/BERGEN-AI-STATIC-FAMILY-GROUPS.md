# Bergen-AI: stable family groups / read-only inventory

Tracking: [Issue #98](https://github.com/tobe4it/bergen-platform/issues/98)

## Working architecture

Use Synology SSO/OIDC for **identity**, not automatic membership writes.
Maintain three mostly stable, separately administered application groups:
a common family group, an adult group, and a child group. Adult accounts
normally belong to *family + adults*, child accounts to *family + children*.
The actual group names stay in ignored site-local Ansible variables.

The existing Open WebUI deployment keeps native OAuth group/role
management disabled, group creation disabled, and new accounts `pending`.
A family membership is not a substitute for explicitly scoped model,
knowledge, tool or Paperless ACLs. Never infer Paperless permissions from
a Bergen-AI group. For v0.12.3, default to **three top-level groups**
rather than nested groups; child-inherits-parent access must not be
accidentally introduced.

## Read-only inventory

New playbook:
`ansible/playbooks/audit-bergen-ai-static-family-groups.yml`

Its **only HTTP requests** are GET
`http://127.0.0.1:3000/api/version` and
`http://127.0.0.1:3000/api/v1/groups/` from the existing
inventory host. Both endpoints exist in reviewed upstream v0.10.2 and
v0.12.3. It requires the exact selected host, a single host per run,
a separate read-only audit approval and a protected Open WebUI admin
bearer token. Any other detected version fails closed.

Both the admin response and group list are suppressed through
`no_log` and processed locally. The printed result reports only
role-labeled categories such as `MISSING`, `PRESENT_ROOT`,
`NESTED_REVIEW_REQUIRED`, `HIERARCHY_UNVERIFIED` or
`PRESENT_LEGACY_FLAT`. No real group names, IDs, member identities,
permission content or raw API responses are printed.

`STATUS=INVENTORY_PRESENT_ONLY` **does not establish access-control
safety**. Group ownership, actual direct/effective members, adult–child
separation, other groups, private model/knowledge ACLs and existing
session revocation still require independent tests.

## Controller execution

Use ignored local variables, not git-tracked inventory and not inline
command-line credentials. Example structure in
`ansible/vars/bergen-ai-family-audit.local.yml`:

```yaml
bergen_ai_family_audit_host: YOUR_EXISTING_BERGEN_AI_INVENTORY_HOST
bergen_ai_family_audit_approved: true
bergen_ai_family_group_expected:
  family: YOUR_EXISTING_COMMON_GROUP
  adults: YOUR_EXISTING_ADULT_GROUP
  children: YOUR_EXISTING_CHILD_GROUP
```

The separate admin API token
`vault_open_webui_admin_token` must be held in encrypted Vault.
Use the same existing inventory/Vault conventions as the effective
configuration audit from PR #100. An admin token may have broad scope
in this Open WebUI version: validate use for this controlled, local
read-only procedure only. Never paste tokens, names or raw group
responses into issue comments.

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-bergen-ai-static-family-groups.yml \
  -e @ansible/vars/bergen-ai-family-audit.local.yml \
  -e @ansible/vars/ai-oidc.vault.yml \
  --vault-id ai@prompt \
  --syntax-check

ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/audit-bergen-ai-static-family-groups.yml \
  -e @ansible/vars/bergen-ai-family-audit.local.yml \
  -e @ansible/vars/ai-oidc.vault.yml \
  --vault-id ai@prompt
```

Expected `changed=0`. If a group is missing, the result is a
**request for manual review**, not permission to create it. If v0.12.3
reports any of the selected groups nested, review inheritance,
effective access and backing ACLs before continuing. No automatic
group provisioning is implemented.

## Acceptance to close #98

1. Read-only effective OIDC configuration audit (#100), plus this
   family inventory on the actual installed version.
2. Explicit identity-to-group roster verified **privately** with
   adult and child test accounts; no shared parent-to-child login.
3. Separate positive and negative **model, knowledge and tool**
   access tests for children and adults, including direct API access.
   Paperless private documents remain inaccessible across boundaries.
4. Document disabling a test account and changing membership, then
   verify the operational revocation procedure for existing Open WebUI
   sessions and API tokens. Changes are rare but must be enforceable.
5. Backups, working local administrator, version-pinned image,
   migration and rollback testing before any Open WebUI upgrade.
6. If an optional later automation is needed, separately review
   specific claims and the absence of reliable empty-claim revocation;
   never silently activate `ENABLE_OAUTH_GROUP_MANAGEMENT`.

This code neither upgrades Open WebUI nor changes production group,
LDAP, OIDC or Paperless settings.
