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

## Multi-installation namespace contract

The logical roles `family`, `adults` and `children` are **stable
semantic keys**, not directory group names. Every household / deployment
has its **own** LDAP base DN, OIDC issuer/tenant and group namespace.
There is no fixed `@...` suffix, shared LDAP domain, naming convention,
claim-value format or universal group UUID.

Three separate identifiers must not be conflated:

1. **Logical role**: `family`, `adults`, `children` (product-internal
   meaning independent of deployment).
2. **IdP/LDAP group identity**: an environment-specific DN, group name,
   UUID or exact OIDC claim value, validated in that tenant. This is
   *not* resolved by the inventory playbook.
3. **Open WebUI group name/ID**: the exact locally existing Open WebUI
   group to which a role is administratively assigned. This is what
   `bergen_ai_family_group_expected` matches using exact string equality.

**Example A, installation with qualified Open WebUI names**
(illustrative non-routable domain, not a Bergen site identifier):

```yaml
bergen_ai_family_group_expected:
  family: "Familie@home-a.invalid"
  adults: "Eltern@home-a.invalid"
  children: "Kinder@home-a.invalid"
```

**Example B, independent installation with neutral local names:**

```yaml
bergen_ai_family_group_expected:
  family: "Shared"
  adults: "Parents"
  children: "Kids"
```

The Identity Provider for B might instead return a DN such as
`cn=Parents,ou=Groups,dc=home-b,dc=invalid`. That is **not** the
Open WebUI group name `Parents`, and this audit must not pretend
they have been synchronized. In another environment the IdP claim
might be a UUID. Group names may even belong to different
namespaces within a single installation.

Keep the OIDC issuer, expected LDAP/SSO claim identifiers, exact
Open WebUI group mapping and all hostnames in site-local protected
inventory/Vault. Do not derive an LDAP/OIDC mapping merely by
appending or stripping a domain. Do not enable native group
synchronization to reconcile a name mismatch. A mismatched qualified
name is reported as `MISSING`, **never matched on the short prefix**.

Future installers can collect these independent per-site identifiers
during setup and verify the intended relationships; they must not
hardcode a specific household's LDAP domain into common roles or
provisioning defaults. IdP authorization, issuer validation, user
membership and Open WebUI resource access still need independent E2E
checks.

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
