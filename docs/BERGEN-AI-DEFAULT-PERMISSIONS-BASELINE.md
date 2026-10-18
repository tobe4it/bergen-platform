# Bergen-AI: Controlled global default-permission baseline (Open WebUI 0.10.2)

Tracking [#98](https://github.com/tobe4it/bergen-platform/issues/98).
This is an **application configuration change**, managed from Ansible rather
than from the UI. The controller run is not performed by CI. This change
does not modify LDAP, OIDC, existing group memberships, user roles or public
resource grants.

## Why this is necessary

The production token-free audit ([#102](https://github.com/tobe4it/bergen-platform/pull/102))
confirmed:

- `ENABLE_PERSISTENT_CONFIG=ON`, `DEFAULT_SOURCE=DATABASE`.
- `web_search`, `image_generation`, `code_interpreter`, `chat.file_upload` default to `ON`.
- Three site-selected family groups exist, `share=false`, and no memberships.
- Open WebUI 0.10.2 merges global defaults and group permissions with
  **OR semantics**: a group setting of `false` does not revoke a global
  `true`.

The global baseline sets exactly four defaults to `false`:

| Key | Desired |
| --- | --- |
| `features.web_search` | `false` |
| `features.image_generation` | `false` |
| `features.code_interpreter` | `false` |
| `chat.file_upload` | `false` |

All other existing `user.permissions` properties are preserved verbatim.
This deliberately changes capabilities of **all non-admin users** until
more specific group allowances are configured. The family/children groups
**still have ON rights**; **DO NOT ADD CHILDREN TO GROUPS YET**. A separate
reviewed group-rights change is required to prevent inheritance from family
and children. Model/knowledge ACLs and effective E2E permissions are separate
acceptance gates.

## Supported write path

In v0.10.2 the Open WebUI admin endpoint
`POST /api/v1/users/default/permissions` calls the app's
`open_webui.models.config.Config.upsert({'user.permissions': ...})`.
Ansible runs that *same internal application ORM method* in the installed
Open WebUI container (`podman exec`), with an exact before/after JSON
comparison. It does **not** issue SQL UPDATE, does not create an API key, and
does not alter OIDC. As an internal API, it must be re-reviewed after a WebUI
upgrade. It bypasses the HTTP route's event publication; prompt existing user
sessions to refresh, and validate effective API access separately.

This workflow does **not** flip persistence during apply or restart the
container. A previously discovered repository drift was corrected in this PR:
the Open WebUI role Quadlet template now renders
`ENABLE_PERSISTENT_CONFIG=True` by default, matching the **observed running
production instance**. This template change is only committed to Git; the
Open WebUI service has **not** been redeployed or restarted by this change.
Review the eventual regular deployment separately, including the current OIDC
drop-in and local/environment configuration, before allowing a restart.

## Security and rollback contract

- Only the explicit inventory host is eligible, and exactly one host must
  match. Open WebUI `/api/version` must return precisely `0.10.2`.
- The running container must expose the expected data mount and enabled
  persistence, with no overridden DB backend.
- The three private site groups must be the only groups, `share=false`,
  and **zero group memberships**; any drift aborts all actions.
- All four baseline flags must be actual JSON booleans.
- `audit` performs only SQLite SELECTs, prints a SHA-256 fingerprint of the
  complete existing `user.permissions`, and never writes anything.
- `apply` needs both explicit approval and that exact fingerprint; stale
  fingerprints abort. If already compliant it makes no changes.
- Before any write, root stores a full copy of the **affected config key**
  (not the entire SQLite database) under
  `/var/lib/bergen-platform/open-webui/`, mode `0700` directory and
  `0600` backup. Never commit or publicly expose this backup.
- The container runs `Config.upsert` and checks its own before/after
  state; the host independently re-reads the database afterward.
- `rollback` requires explicit approval, the current fingerprint, and
  the prior apply's `ROLLBACK_SELECTOR`. It fails closed on any later edits
  or any group membership. If memberships have already been added, restoring
  permissive defaults may re-enable child capabilities, so a manual security
  review is necessary instead.
- If a write partially succeeds and postverification fails, **do not retry
  blindly**: re-run audit, investigate and, if safe, use the guarded rollback.
- No automatic session revocation is claimed. Re-test permissions through
  each account, including denials.
- This controls one application setting only; full application backup,
  restoration, and container lifecycle remain existing platform operations.

## Run from bp-controller

Work on the isolated PR branch/worktree and use the existing private
inventory. The private role-map file created for #102 is already ignored:

`ansible/vars/bergen-ai-family-audit.local.yml`

It contains `bergen_ai_family_audit_host`,
`bergen_ai_family_audit_approved: true`, and the three actual
`bergen_ai_family_group_expected` entries. Do not commit its contents.

First run the **nonmutating** fingerprint audit:

```bash
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-ai-family-audit"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-bergen-ai-default-permissions.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml
```

Review `STATUS=BASELINE_READY`, the four current flags and
`CURRENT_SHA256`. If defaults are already restricted, expect
`BASELINE_ALREADY_RESTRICTED`. Review the functional impact first.

Explicitly approved **apply** (replace the fingerprint with the audit result):

```bash
CURRENT_SHA256='<paste-exact-audit-CURRENT_SHA256>'
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-bergen-ai-default-permissions.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml \
  -e bergen_ai_defaults_action=apply \
  -e bergen_ai_defaults_approved=true \
  -e "bergen_ai_defaults_expected_sha256=$CURRENT_SHA256"
```

The apply confirms `STATUS=BASELINE_APPLIED` or
`STATUS=ALREADY_COMPLIANT`. Record the returned `CONFIG_SHA256` and,
for an actual change, `ROLLBACK_SELECTOR` in an appropriate restricted
operations log (not in public issues).

Re-run the first audit and confirm all four baseline flags `OFF` and
`STATUS=BASELINE_ALREADY_RESTRICTED`; then conduct non-admin negative
access tests. Do not add children to groups before family and children
group permissions are restricted.

In an emergency, **only if groups remain empty and the previous state is
safe to restore**, use the exact post-apply fingerprint and stored selector:

```bash
POST_SHA256='<paste-exact-post-apply-CONFIG_SHA256>'
ROLLBACK_SELECTOR='<paste-exact-apply-ROLLBACK_SELECTOR>'
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-bergen-ai-default-permissions.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml \
  -e bergen_ai_defaults_action=rollback \
  -e bergen_ai_defaults_approved=true \
  -e "bergen_ai_defaults_expected_sha256=$POST_SHA256" \
  -e "bergen_ai_defaults_rollback_selector=$ROLLBACK_SELECTOR"
```

`--check` may be used only with `action=audit`. For mutating actions
the playbook rejects check mode rather than pretending to apply or rolling
back changes.

## Acceptance gates

1. Offline CI unit tests (including no-change audit, stale fingerprint,
   idempotent repeat, backup and rollback, 3-group/empty-member gate, and
   preservation of unrelated permission flags).
2. Controller `ansible-playbook --syntax-check`.
3. Approved controller read-only audit and reviewed live fingerprint.
4. Explicit approved apply, independent read-back and negative access tests.
5. Separate group-rights PR and tests before approving group memberships.

Do not merge a write-authorizing change until its guardrails and controller
preflight have been reviewed.
