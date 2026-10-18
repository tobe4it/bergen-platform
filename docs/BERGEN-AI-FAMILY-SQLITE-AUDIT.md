# Bergen-AI family groups: token-free SQLite inventory (v0.10.2)

Tracking: [Issue #98](https://github.com/tobe4it/bergen-platform/issues/98).
Complements the existing API-based inventory from PR #101; it does not activate
OAuth group management and does not replace authorization/end-user tests.

## Verified site findings, 2026-10-18

- Open WebUI reported version `0.10.2`; live Podman data volume maps to
  `/app/backend/data` from `/srv/ai/open-webui`.
- Three family groups exist; all owned by the administrator, with zero group
  members, zero group resource grants, and `share=false`.
- There are three accounts (one admin, one user, one pending), and no API keys.
- Runtime `ENABLE_PERSISTENT_CONFIG` is **enabled**, and the effective
  `user.permissions` default source is the database. Defaults for web search,
  image generation, code interpreter, and file uploads currently read **ON**.
- These data are a point-in-time observation, **not a test result from the new
  repository playbook**. Always rerun after changes.

The source of truth for groups and member identity remains the approved Synology
directory/SSO. Open WebUI group membership stays static pending proven revocation.
The actual names of the three selected site groups belong only in ignored local
Ansible variables, never in committed documentation or GitHub issue output.

## Execute on bp-controller

From the checked-out branch containing this playbook, in the same existing
inventory context as the approved OIDC release, place these **local private**
values in `ansible/vars/bergen-ai-family-audit.local.yml`:

```yaml
bergen_ai_family_audit_host: YOUR_EXISTING_AI_INVENTORY_HOST
bergen_ai_family_audit_approved: true
bergen_ai_family_group_expected:
  family: YOUR_EXACT_DIRECTORY_FAMILY_GROUP
  adults: YOUR_EXACT_DIRECTORY_ADULT_GROUP
  children: YOUR_EXACT_DIRECTORY_CHILD_GROUP
```

`ansible/vars/bergen-ai-family-audit.local.yml*` is ignored by Git. Confirm
`git check-ignore` before writing the file. Do not embed credentials in it.

Use the protected inventory from the existing controller checkout, not a copy in
the separate Git worktree:

```bash
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-ai-family-audit"
PLAY=ansible/playbooks/audit-bergen-ai-family-sqlite-readonly.yml

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  "$PLAY" --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml \
  --syntax-check

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  "$PLAY" --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml
```

The script is sent as the `python3 -c` argument using Ansible's `command`
module; **site group names are passed via stdin**, not a remote shell command
line. No credentials, real names, IDs, raw group permissions or responses are
printed. The remote script inspects the container's live mount and database
override settings, opens SQLite in `mode=ro` with `PRAGMA query_only=ON`, and
issues only SELECT statements. All execution tasks set `changed_when: false`
and `no_log: true`. Unsupported app versions, schema changes, alternate DB
backends or mount layouts fail closed. Expected result: `changed=0`.

## Interpretation

`STATUS=INVENTORY_PRESENT_ONLY` means the three named groups are uniquely
present, owned by an admin and set to `share=false`. It **does not** establish
security of effective access. Membership, model/knowledge/tool access, public
access outside the group-grant table, OIDC claim behavior, sessions and token
revocation remain separate acceptance gates.

In Open WebUI v0.10.2, permissions merge **additively** across global user
defaults and all groups (`True` wins). A `False` on the children group does
not override an already-true global permission or a permission granted by the
common family group. Before any child membership, require a reviewed
least-privilege default baseline, version-specific regression tests and direct
negative access checks.

**Do not try to enforce defaults by silently setting
`ENABLE_PERSISTENT_CONFIG=false`.** The live system reads persistent DB
configuration today; flipping the setting could change unrelated functional and
security settings. A separately reviewed, version-pinned Ansible apply workflow
must compare effective settings, require explicit approval, verify backups and
rollback, and use supported application interfaces. Do not write raw SQLite to
manage users, groups or permissions.

No production changes are authorized by this inventory.
