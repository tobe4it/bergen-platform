# Portable Synology → Paperless Scan Ingestion

The NAS-side programs are reusable: no NAS hostname, LDAP home, source
directory, destination host, or account is hard-coded in the Python code.
Only a non-secret site-local configuration selects them.

## Repository components

- `ansible/files/paperless/synology_config.py` — validated root-owned config loader
- `ansible/files/paperless/synology_scan_sync.py` — fail-closed PDF sender and durable journal
- `ansible/files/paperless/synology_inotify_watch.py` — Linux inotify and 15-minute recovery sweep
- `ansible/files/paperless/synology_watcher_supervisor.py` — single-instance boot supervisor
- `ansible/playbooks/prepare-paperless-synology-portable.yml` — safely stage all five files, inactive
- `ansible/vars/paperless-synology.example.yml` — copyable sample site configuration

The site configuration `ansible/vars/paperless-synology.local.yml`
and `ansible/vars/paperless.vault.yml` are gitignored. Never commit
real hostnames, LDAP home layouts, local SSH keys or secrets to the
generally distributed module.

**Migration:** The earlier per-component Ansible playbooks are meant
for the original proof of concept. After switching to the generic
code, deploy only with `prepare-paperless-synology-portable.yml`;
the Python modules require the new JSON config next to the code.

## Local setup

Copy `ansible/vars/paperless-synology.example.yml` to
`ansible/vars/paperless-synology.local.yml`, and edit it with `vim`.

- `synology_admin`: controller-to-NAS administrative SSH principal.
- `synology_config.sync_user`: existing restricted DSM account.
- `state_root`: root-owned root of storage volume, `0755`.
- `state_parent`: root-owned `0755` private application parent directly
  under the storage volume.
- `sources`: absolute NAS input directories and matching pre-authorized
  Paperless staging scopes. A new NAS scope does NOT provision a corresponding
  Paperless group, workflow or access permission; that must be configured
  separately.
- `ssh_identity`: private key location on NAS. `~/.ssh/...` is resolved
  relative to `sync_user`'s home.
- `destination`: restricted SSH+rsync receiver address.
- `quiet_seconds`, `max_size_bytes`, `max_files_per_run`,
  `quiet_after_event_seconds`, `full_scan_seconds`,
  `sender_timeout_seconds`: validation thresholds and scan cadence.

Keep the existing `state_parent/sync_user` private journal directory
(`0700`, sync-user owned) and its receipts intact during migration.
Otherwise the sender may attempt to resend already imported files.
The activation gate `state_parent/synology-sync.enabled` must be
absent during deployment. No input PDFs are deleted or renamed.

The NAS config is stored root:root `0644` at
`state_parent/bin/synology-paperless.json`, alongside the root-owned
Python modules. The configuration has no credentials; actual private
SSH keys stay on the NAS under the restricted account.

## Stage and probe — no transfers

From `bp-controller` (or another Ansible controller with SSH access):

```bash
cd ~/bergen-platform
git fetch origin
git merge --ff-only origin/feat/paperless-ingest-bridge-20261014

cp -n ansible/vars/paperless-synology.example.yml \
  ansible/vars/paperless-synology.local.yml
vim ansible/vars/paperless-synology.local.yml

python3 -m py_compile \
  ansible/files/paperless/synology_config.py \
  ansible/files/paperless/synology_scan_sync.py \
  ansible/files/paperless/synology_inotify_watch.py \
  ansible/files/paperless/synology_watcher_supervisor.py

ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-synology-portable.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml \
  --syntax-check

ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-synology-portable.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  -e @ansible/vars/paperless-synology.local.yml
```

Expected: `NAS_PORTABLE_PREFLIGHT_OK`, byte-identical checksums
for the four modules and config, a sender `TRACKED`/`READY` report,
`INOTIFY_PROBE_OK` with the configured number of directories, and
confirmation that the enable gate is absent. The kernel probe writes
a disposable non-PDF file only inside the private state directory.
There is no DSM task creation, boot watcher launch or live transmission.

## Boot configuration, only after successful probe

Create a disabled DSM **Triggered Task → Boot-up**, user = configured
`sync_user`. Script (adjust to the site-specific path):

```sh
umask 077
exec python3 -u /volume1/.paperless-state/bin/synology_watcher_supervisor.py --boot >> /volume1/.paperless-state/paperless-sync/watcher.log 2>&1
```

If DSM does not offer the restricted account, use a separate, reviewed
launcher that switches from root to that account **before** invoking
Python and opening logs. Do not run the worker as root.

The supervisor waits for the root-owned activation gate. Only after
reviewing the `READY` backlog and authorizing every configured scope
should an administrator create the enable gate and enable the task.
Then the supervisor launches the watcher, which triggers an initial
full reconciliation, listens for completed file writes and renames,
and performs a full recovery scan every 15 minutes by default.

On error, remove the gate, stop/disable the DSM task, inspect logs and
receipts. Do not delete `PREPARED` receipts or blindly retry uncertain
transfers; verify destination checksum and Paperless import status.

For the original instance-specific procedure, see
`docs/PAPERLESS-SYNOLOGY-INOTIFY.md`.
