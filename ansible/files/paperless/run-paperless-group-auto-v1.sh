#!/usr/bin/env bash
# Unattended GROUP-only v1 archive invocation from systemd credentials.
# No credentials are stored in Git or passed as an argv value.
set -euo pipefail
umask 077

readonly WORKTREE=/home/ansible/bergen-platform-pr81
readonly HOME_REPO=/home/ansible/bergen-platform
readonly VAULT_FILE="${1:-}"
readonly VENV_ANSIBLE="$HOME_REPO/.venv/bin/ansible-playbook"

[[ "$(id -un)" == ansible ]] || { echo "REFUSE_WRONG_SERVICE_ACCOUNT" >&2; exit 2; }
[[ "$#" -eq 1 && -n "$VAULT_FILE" && -r "$VAULT_FILE" && -f "$VAULT_FILE" && ! -L "$VAULT_FILE" ]] ||
  { echo "REFUSE_MISSING_SYSTEMD_VAULT_CREDENTIAL" >&2; exit 2; }
[[ -x "$VENV_ANSIBLE" ]] || { echo "ANSIBLE_VENV_NOT_FOUND" >&2; exit 2; }
[[ -d "$WORKTREE/.git" || -f "$WORKTREE/.git" ]] ||
  { echo "PAPERLESS_WORKTREE_NOT_FOUND" >&2; exit 2; }

cd "$WORKTREE"

# One verified, finished Paperless import per invocation. The playbook
# fails closed before any archive move on incomplete NAS/Paperless evidence.
# No private scope or retention expiry is authorized.
exec "$VENV_ANSIBLE" \
  -i ansible/inventory.yml \
  -i "$HOME_REPO/ansible/inventory.local.yml" \
  ansible/playbooks/archive-next-verified-paperless-group-v1.yml \
  --vault-id "paperless@$VAULT_FILE" \
  -e "@$HOME_REPO/ansible/vars/paperless.vault.yml" \
  -e "@$HOME_REPO/ansible/vars/paperless-synology.local.yml" \
  -e '{"paperless_group_auto_archive":true,"paperless_archive_commit":true}'
