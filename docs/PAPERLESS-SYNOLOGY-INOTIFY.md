# Synology Paperless: inotify + 15-minute recovery scan

Status: **prepared, disabled** until the explicit activation gate is created
and the DSM Boot-up task is enabled. Managed in PR #60.

## Data flow

Synology PDF -> inotify IN_CLOSE_WRITE / IN_MOVED_TO -> wait 65 seconds ->
existing synology_scan_sync.py --scheduled --commit -> SSH+rsync ->
Paperless staging -> two active systemd timers -> Paperless importer +
authorization reconciliation.

The watcher checks `Privat/thomas`, `Privat/nadja`, `Eltern` and
`Familie`. Every 900 seconds it does a complete reconciliation even
without events, including after inotify queue overflow. The existing
sender independently enforces 60 seconds of stable mtime/ctime, PDF header,
EOF, SHA256, file snapshot, journal and 100 new candidates per run.
No source documents are deleted or renamed. No extra DSM package required.

An event does not bypass the sender's journal, SSH restrictions, group
authorization, or enable gate. If an inotify watch is invalidated, the
worker stops and the startup supervisor restarts it after 60 seconds.
A single-instance lock prevents duplicate startup supervisors.

**Important operational limitation:** The 60-second quiescence heuristic
alone cannot mathematically prove that a writing process has finished;
the watcher prefers close-write / completed moves, but the 15-minute
rescan can still encounter a file held open with no recent writes.
Scanning applications should write to a temporary name and rename a
completed PDF into its input directory whenever possible.

## Install and probe (does not activate)

On `bp-controller`, after fetching the feature branch:

```bash
cd ~/bergen-platform
git fetch origin
git merge --ff-only origin/feat/paperless-ingest-bridge-20261014

python3 -m py_compile \
  ansible/files/paperless/synology_scan_sync.py \
  ansible/files/paperless/synology_inotify_watch.py \
  ansible/files/paperless/synology_watcher_supervisor.py

# The sender must be deployed at the exact reviewed version first.
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-synology-scan-sync.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml

ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-synology-inotify.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml \
  --syntax-check

ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-synology-inotify.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml
```

Expected `NAS_DEPLOY_PREFLIGHT_OK`, source-hash checks,
`INOTIFY_PROBE_OK 4 source watches`, and no enable gate. The kernel
self-test creates only a temporary `probe.txt` below the **private
journal state**, not in any user's input directory. No rsync runs.

Installed root-owned files:

- `/volume1/.bergen-platform-state/bin/synology_scan_sync.py`
- `/volume1/.bergen-platform-state/bin/synology_inotify_watch.py`
- `/volume1/.bergen-platform-state/bin/synology_watcher_supervisor.py`

Source journal is private to `paperless-sync` under
`/volume1/.bergen-platform-state/paperless-sync/`.

## DSM start at boot

DSM Control Panel -> Task Scheduler -> Create -> **Triggered Task** ->
**User-defined script** -> trigger/event **Boot-up** (labels vary by DSM).

Task name: `Bergen Paperless Inotify`.

Prefer running the task **as `paperless-sync`**, if selectable. Its
custom script is:

```sh
umask 077
exec /usr/bin/python3 -u /volume1/.bergen-platform-state/bin/synology_watcher_supervisor.py --boot >> /volume1/.bergen-platform-state/paperless-sync/watcher.log 2>&1
```

If DSM only allows a privileged scheduled-task user, configure the DSM
Boot-up task as `root` with an **explicit immediate identity drop**:

```sh
sudo -n -H -u paperless-sync /bin/sh -c 'umask 077; exec python3 -u /volume1/.bergen-platform-state/bin/synology_watcher_supervisor.py --boot >> /volume1/.bergen-platform-state/paperless-sync/watcher.log 2>&1'
```

In this variant the Python process and log redirection occur only
**after** changing to the dedicated unprivileged account. Do not run the
supervisor or watcher directly as root. First verify in a separate
shell that `sudo -n -H -u paperless-sync python3 --version` works.

**Save the DSM Boot-up task disabled initially.** Keep the task
configuration and authorization separately approved. The supervisor
waits for the root-owned enable gate; it does not create one.

## Explicit activation after review

Check the remaining `READY` PDFs and their intended scopes. Creating
the gate enables all enabled scopes, not only the test documents.
After approving the backlog, as `supervisor` on the NAS use
`sudo -n` to create a regular root-owned `0644` gate file:

```sh
sudo -n install -o root -g root -m 0644 /dev/null \
  /volume1/.bergen-platform-state/synology-sync.enabled
```

Do this only after the gate is confirmed absent. Enable the DSM
Boot-up task and trigger it once manually (or reboot). On each start
the supervisor obtains `watcher-supervisor.lock`, launches the worker
and restarts it after unexpected failure. Worker startup itself triggers
the first full sync; every 15 minutes another full sync runs.

Check private log with `sudo -n tail -n 100
/volume1/.bergen-platform-state/paperless-sync/watcher.log`. Watch for
`WATCHER_SUPERVISOR_STARTED`, `INOTIFY_WATCH_READY`,
`SYNC_START STARTUP`, `SYNC_END STARTUP rc=0`, and later
`SYNC_START PERIODIC_15_MIN`. `READY` becomes `SENT` in the NAS
journal; the Paperless-side reconcile receipts then reach `IMPORTED`.
The log includes document names: keep it private, rotate it periodically.

## Emergency stop / recovery

- First remove the root-owned gate, thereby blocking **every**
  scheduled sender invocation (the worker verifies it independently).
- Stop/disable the DSM Boot-up task, then inspect the log and receipts.
- Do not delete `PREPARED` or `SENT` journal entries. Resolve
  ambiguous transfers against destination hash + Paperless receipt.
- The next clean restart performs an immediate rescan; the 15-minute
  sweep provides recovery from events missed during operation.

Known pre-activation items (last dry-run 2026-10-14):
`Privat/thomas/BR2 Mensch geht vor.pdf`,
`Privat/thomas/Gescanntes Dokument.pdf`,
`Familie/Katherina Reiche- Handelt Katherina Reiche wie eine Klimaleugnerin? | DIE ZEIT.pdf`.
Recheck rather than relying on this list as current truth.
