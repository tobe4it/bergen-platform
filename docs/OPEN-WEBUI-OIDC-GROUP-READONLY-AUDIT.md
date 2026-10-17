# Open WebUI OIDC group synchronization: read-only ENV audit

This is a safety extraction from historical PR #73. **It does not enable group
synchronization, provision groups or prove group revocation**. The runtime
environment can differ from effective Open WebUI settings stored in its database
if persistent configuration is enabled.

Site-local requirements (kept out of Git):
- Exact approved Proxmox inventory hostname: `open_webui_oidc_audit_pve_host`
- Existing unprivileged guest VMID: `open_webui_oidc_audit_vmid`
- Exact guest hostname: `open_webui_oidc_audit_guest`

Put these in an ignored Ansible variables file. Keep secrets out of command-line
`-e key=value` values. Never include OIDC tokens or claims in audit output.

From the controller, after reviewing the inventory:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-open-webui-oidc-group-env-readonly.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/ai-oidc-audit.local.yml --syntax-check

ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-open-webui-oidc-group-env-readonly.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/ai-oidc-audit.local.yml
```

If the inventory uses a different vault ID, provide that ID instead.

The task verifies the Proxmox target, the expected LXC hostname and service
status, then classifies six **container environment** variables. It emits no
actual group names, user accounts, tokens, claims, OIDC endpoints or settings
files. `changed=0` is expected. If a check fails, investigate; **do not
start** the older mutating PR.

**Critical distinction:** `ENABLE_OAUTH_GROUP_MANAGEMENT=false` in a
container's environment does not conclusively prove the feature is disabled
at runtime if `ENABLE_OAUTH_PERSISTENT_CONFIG` or saved application settings
override environment values. A separate sanitized inspection of *effective*
settings and negative authorization tests is mandatory before contemplating
activation.

A missing/empty `groups` OIDC claim may not remove previously synchronized
membership in Open WebUI v0.10.2. That revocation behavior and every
client-specific permission boundary require separate E2E validation.

Security and implementation requirements: issue #98. No restart, RBAC change
or automatic provisioning is authorized by this playbook.
