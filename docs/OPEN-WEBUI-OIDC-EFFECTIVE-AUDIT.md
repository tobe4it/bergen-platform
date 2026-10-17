# Bergen-AI OIDC group authorization: effective, read-only audit

Tracking: https://github.com/tobe4it/bergen-platform/issues/98
Source revision reviewed: Open WebUI v0.10.2
Original mutating group-setup PR #73: closed without merge.

## Why the current native group sync cannot be treated as revocation

In Open WebUI v0.10.2, \`update_user_groups\` runs on successful OAuth
login only. In its removal/addition loops, it requires a nonempty
\`user_oauth_groups\` list. Absent \`groups\`, \`groups: []\`, an empty
string, and malformed non-list claims therefore leave previously assigned
groups unchanged. Nonempty claims may remove **any unblocked current group**
not in the provider claim, not just the approved family roles. Members may
also retain access in existing application sessions until an independent
session/token revocation or expiry is proven.

Reviewed source:
https://github.com/open-webui/open-webui/blob/v0.10.2/backend/open_webui/utils/oauth.py

**Do not enable \`ENABLE_OAUTH_GROUP_MANAGEMENT\` for privileged parent/child
authorization based only on the presence of a \`groups\` claim.**

## Which read-only audit to use

The earlier \`audit-open-webui-oidc-group-env-readonly.yml\` audits the
container environment through Proxmox, **not effective running settings**.

The new \`audit-open-webui-oidc-effective-readonly.yml\` queries the
**running application's authenticated admin GET endpoints** on the
existing guest's loopback:
- GET \`/api/version\`
- GET \`/api/v1/auths/admin/config/oauth\`
- GET \`/api/v1/auths/admin/config\`
- GET \`/api/v1/auths/admin/config/ldap\`

These use Open WebUI's \`Config.get\` runtime read path on v0.10.2,
taking OAuth persistence behavior into account. The endpoints can return
client secrets, URLs, group names or private admin settings. Hence
**the raw responses and authorization header are always \`no_log: true\`**,
including failures. Only eight predefined, bounded classifications and
three safety/disclaimer flags are printed.

The audit is non-mutating and makes no LDAP/OIDC login, changes no
permission, provisions no group and restarts no service. Admin access
through a protected API token is necessary: if a read-only admin token
cannot authenticate, **do not change authentication settings to work
around the failure**. Existing local administrator login remains
available for manual review.

## Controller procedure (no live service changes)

From a current clean \`bergen-platform\` checkout on \`bp-controller\`,
review the encrypted credentials and site-local ignored variables.

In \`ansible/vars/ai-oidc-effective-audit.local.yml\` (ignored by Git),
provide exactly these two values, selecting the single actual inventory
host:

\`\`\`yaml
open_webui_oidc_effective_audit_host: YOUR_EXISTING_AI_INVENTORY_HOST
open_webui_oidc_effective_audit_approved: true
\`\`\`

Keep a **dedicated admin API bearer token** as
\`vault_open_webui_admin_token\` in the ignored encrypted
\`ansible/vars/ai-oidc.vault.yml\`; ensure it has only the required
permissions where the installed version supports scoped API keys.
Never paste that token into chat, the CLI, Git or debug output.
This admin token is not the OIDC client secret.

Example commands (edit inventory paths if the controller uses different
private inventory names):

\`\`\`bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-open-webui-oidc-effective-readonly.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/ai-oidc-effective-audit.local.yml \
  -e @ansible/vars/ai-oidc.vault.yml \
  --syntax-check

ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-open-webui-oidc-effective-readonly.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/ai-oidc-effective-audit.local.yml \
  -e @ansible/vars/ai-oidc.vault.yml
\`\`\`

Expected \`changed=0\`. A failure is an **audit blocker**, not
authorization to set any enable flag, restart Open WebUI, or relax
endpoint authentication. A reported \`UNREVIEWED_VERSION\` requires
version-specific code review first.

The emitted \`OIDC_EFFECTIVE_*\` flags are **the effective OAuth settings
as returned through the admin API**, not an external authorization
decision. \`OIDC_EFFECTIVE_GROUP_MAPPING=DISABLED\` is the safe
pre-activation state. A value of \`ENABLED\` calls for independent
read-only investigation, not automatic overwrite.

## Mandatory authorization acceptance after the audit

Before any live group sync, use **synthetic identities and separate
test groups**, with saved copies of admin/LDAP access and backups:
1. Confirm the OIDC \`groups\` claim is issued to the correct subject;
   only allowlisted groups are mapped, never admin role promotion.
2. Test a valid changed claim, an empty/missing claim and malformed
   claims; child accounts must not inherit parent group privileges.
3. Test account disablement, a removed LDAP membership and continued
   *existing* browser sessions and direct API bearer tokens, not just
   logout/login. Define and measure the maximum allowed revocation delay.
4. Test model, workspace/knowledge and connected-tool ACLs. Paperless
   document permissions are **independent** and must not be inferred
   from Open WebUI group membership.
5. Refuse activation unless all revocation pathways (including absent
   claims and existing sessions) demonstrably fail closed. If Open
   WebUI cannot enforce that, retain native group sync **disabled**
   and design a separate request-time authorization boundary.
6. Any later activation requires a **separate** explicit operator
   approval, snapshot/restore procedure, tested local break-glass
   access and a verified rollback. Never merge a privilege-bearing
   group synchronizer as a side effect of accepting this audit.

The previous standard environment audit and this admin-API audit are
complementary, not interchangeable.
