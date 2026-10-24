# Daily OS security updates and change reports

Status: implementation; live deployment and delivery must be verified on the
controller. Nothing in this change asserts that production PHP is patched.

## Scope and policy

The runner enumerates **all hosts in all configured inventories**, including hosts
without host variables. This is not network discovery: unlisted machines need to
be added to the local inventory. The historical inventory contains an `ansible-old`
local alias: exclude it explicitly if it duplicates the current controller.
Existing MQ systems live in a separate repository; this does not change MQ policy.

Each host has one explicit policy in a private JSON file: `security`, `audit`, or
`excluded` (with reason). Unknown hosts default to audit and are reported. Put an
explicit low-impact security host in `canaries`; subsequent hosts are processed
sequentially. A failed/unreachable host stops further installations, but other
hosts are still audited. Audit refreshes metadata; it does not install packages.

Proxmox nodes, controllers, database servers and appliances should initially use
`audit` until their application-specific checks, maintenance and backup policy
are established. No automatic reboot, repository change, crypto-policy change,
major application upgrade or container image replacement is performed. Weekly
nonsecurity updates are not implemented by this security-only workflow.

### Security coverage

APT uses python3-apt, trusted Debian/Debian-Security or Ubuntu origins for the
running release's security suite, exact versions, held-package detection,
`--only-upgrade`, `--no-remove` and a simulated transaction before installation.
Dependencies may also change; the before/after package inventory records them.
APT preferences/repository suitability must be reviewed before enabling a host.
Configuration files are preserved with force-confdef/force-confold; .dpkg-dist
files may need manual reconciliation. Third-party/ESM suites are not covered.

DNF uses Ansible's security filter and requires `dnf_metadata_verified: true` only
after checking that relevant repositories publish usable updateinfo. Zero
candidates never proves that third-party software has no vulnerabilities.
Requires the distribution's Python DNF bindings. DNF5 needs compatible Ansible.

Reboot reporting uses Debian's marker where present and DNF needs-restarting.
A missing Debian marker is only a marker result, not proof that all processes use
new libraries; nonstandard kernels/services need separate checks. The standalone `/usr/bin/needs-restarting` checker is used when installed; its
absence is treated as unknown, not a clean result. LXC kernel updates belong
to the host. No automatic rollback is attempted after partial transactions.

## Controller prerequisites

- Dedicated clean checkout of this branch/commit (no automatic git pull in timer).
- Python 3 and ansible-core 2.19.x in the existing controller virtualenv.
- Existing inventory files, verified SSH host keys, noninteractive SSH and become.
- If needed, `vault_password_file` points to an existing private, noninteractive
  credential file; never pass passwords on command lines or store in Git.
- A current recoverable backup according to each application's policy. This
  workflow does not create or independently prove backups.
- Debian/Ubuntu: python3-apt already installed on managed hosts.

## Private configuration

Use `scripts/configure_system_updates.py --help` to create the private configuration
with a hidden SMTP password prompt, or copy
`ansible/examples/system-updates/config.json.example` to
`~/.config/bergen-updates/config.json`, mode 0600; directory mode 0700. Replace
absolute paths for the actual controller account and available inventory files.
Set SMTP host, username, sender and recipient to the agreed Bergen-Mail values.
Password belongs in a separate mode-0600 file referenced by `password_file`.
No password is printed or included in mail reports. STARTTLS and certificate
verification are mandatory. The runner never sends through Gmail.

A host policy looks like this (replace service/URL placeholders with live values):

```json
"policies": {
  "canary-host": {
    "mode": "security",
    "restart_services": ["php8.2-fpm", "nginx"],
    "health_urls": ["https://application.example.net/status.php"]
  },
  "hypervisor": {"mode": "audit"},
  "old-alias": {"mode": "excluded", "reason": "Duplicate controller alias"}
},
"canaries": ["canary-host"]
```

Service names and URLs are illustrative, not auto-detected live facts. All listed
health URLs must return HTTP 200 with valid TLS before/after the transaction.
Checks run from the managed host; choose unauthenticated minimal health endpoints
without secrets in URLs. Include every relevant long-running consumer in restart
policy. Package scripts can also restart services during installation. Security
hosts without restart/check policy are rejected before updating anything.

## First run and activation

From the clean dedicated checkout:

```sh
python3 scripts/system_updates.py --config "$HOME/.config/bergen-updates/config.json" --audit-only
```

Confirm inventory completeness, operating systems, security source coverage,
backups, service checks, and actual delivery to the recipient. Update the private
host policies, then execute the first policy run:

```sh
python3 scripts/system_updates.py --config "$HOME/.config/bergen-updates/config.json"
```

Install the scheduler using the existing virtualenv and inventory. The role
requires a private config owned by `ansible` and a clean checkout at
`/home/ansible/bergen-platform-updates` by default. Override role variables for
other paths/accounts. Never copy the example paths blindly to a different user.

```sh
../bergen-platform/.venv/bin/ansible-playbook \
  -i ../bergen-platform/ansible/inventory.yml \
  ansible/playbooks/install-system-update-scheduler.yml --limit bp-controller
systemctl status bergen-system-updates.timer
systemctl list-timers bergen-system-updates.timer
```

Default: daily **04:15 Europe/Berlin**, up to five minutes randomized delay,
missed runs caught up after reboot. Installation enables the timer; an immediate
manual first run above verifies actual operation. Existing apt/dnf timers are not
disabled. Avoid overlapping patch managers; package locks are never removed.

## Change evidence and failure handling

Every run writes mode-0600 JSON, text, HTML and MIME mail into a private run
subdirectory. The report includes UTC start/end, unique ID, Git commit, config
fingerprint, per-host policy/status, package before/after differences, explicit
service restarts, reboot marker, checks, pending holds and follow-up priorities.
No raw Ansible output, environment or inventory hostvars is attached. Advisory/CVE
IDs are explicitly marked uncollected; no unsupported CVE-remediation claim.

The SMTP delivery record distinguishes server acceptance from actual inbox
receipt. Run exit codes: 0 completed (may contain warnings), 1 update/observer
failure, 2 delivery failure, 3 overlapping run. Failed mail keeps the original
report. Retry **mail only**, without rerunning package transactions:

```sh
python3 scripts/system_updates.py --config "$HOME/.config/bergen-updates/config.json" \
  --retry-report "$HOME/.local/state/bergen-updates/RUN_ID/report.json"
```

A timeout means remote state is unknown; inspect package manager processes/locks
before another run. The systemd journal records bounded failure categories.
Private reports have no automatic retention deletion; include them in storage
capacity/retention policy. Never commit reports or SMTP credentials.

## Independent watchdog

Install a second dedicated checkout and private SMTP config on an **independent
machine**, not merely another service on the controller. Add this config section:

```json
"watchdog": {
  "ssh_target": "ansible@bp-controller",
  "heartbeat_path": "/home/ansible/.local/state/bergen-updates/last-completed.json",
  "max_age_hours": 30
}
```

Verify noninteractive SSH with known host keys and least-privilege read access to
that heartbeat. Run `scripts/system_updates.py --config CONFIG --watchdog` on the
observer. Install the same scheduler role with `system_update_scheduler_watchdog:
true`, `system_update_scheduler_calendar: '*-*-* 09:00:00 Europe/Berlin'`, observer
paths/user and an inventory mapping the selected observer into `controllers` for
this installation only. It sends an alert if the controller is unreachable or the
last completed-and-SMTP-accepted run is older than 30 hours. A fresh error report
already alerts through the normal run. Monitoring is **not active until this
second installation is completed**. If Bergen-Mail itself fails, independent
mail delivery is unavailable too; use an external monitoring channel for that.

## Validation

### Combined operating report and central syslog evidence

`scripts/configure_system_operations.py --config CONFIG --syslog-host INVENTORY_ALIAS`
enables a second read-only evidence phase after the package phase, including when
an individual update task failed. To read a syslog LXC through an already trusted
Proxmox connection, additionally supply `--syslog-ctid CTID --expected-hostname
EXPECTED_GUEST_HOSTNAME`; the target host is then the Proxmox inventory alias.
The guest hostname is verified before reading logs. This avoids inventing a
collector IP or automatically accepting a new SSH host key. A direct collector
alias is also supported and verifies the same expected hostname.

Metrics include 1m CPU load, RAM from MemAvailable, bounded real filesystem usage,
selected and failed systemd units, Postfix queue count (without sender/recipient),
Rspamd availability/numeric counters when available, rootful Podman/Docker state,
and aggregate WireGuard handshake counters (without any keys or endpoints).
Rootless container scope is not claimed. Read-only RPM version comparison detects
an installed kernel newer than the running installed kernel, overrides an earlier
`NOT_REQUIRED` result and reports `REQUIRED`; no restart is performed. A filesystem
at >=90% is critical; >=80% is a warning. Read-only probes are time/output bounded.

CVE hints use existing DNF cache (`updateinfo info --security`) or an installed
debsecan. Missing tools, failed queries and unverified cache freshness are explicit.
No vulnerability scanner or dependency is installed. CVE absence is not proof of
patch completion. The literal `--cve CVES` from the old report is not reused.

System and application log summaries come only from the central collector's
`/var/log/remote/*.log` and first uncompressed rotation. ISO-8601/RFC5424 timestamps
are filtered to the most recent 24h; legacy timestamps without year/timezone are
reported as unparsed rather than assigned a guessed date. At most 128 files,
4 MiB per file and 15 seconds of central scanning are used. Counts are explicitly
sampled when capped; compressed rotations and exhaustive daily event counts are
not claimed. Association uses unique syslog header hostnames, not filename/IP
guesses; sender authentication is not inferred. Additional exact names can be
supplied in `operations.log_names` per inventory alias. Shared/ambiguous hostnames,
no recent data and unreachable collectors become visible warnings.

Only fixed event categories/counts and source filenames leave the collector;
mail addresses, message content, raw log lines and WireGuard secrets are omitted.
There is no local journal/container-log fallback hiding a missing central feed.
Mailman and forwarded container events are covered when present in that feed;
forwarding itself is not deployed by this change. All evidence is included in
the existing HTML/plaintext email and JSON attachment, with separate operating
and syslog status columns. Operations failures do not discard the package report
or prevent an attempt to send the consolidated email.

The private config helper backs up the old config and is idempotent. The old
root cron (`0 7 * * * ansible-playbook /root/server_report.yml -i localhost,`)
remains in place until a received combined report proves host/section/log coverage
and the daily controller schedule is active. Its removal is a separate verified
cutover. This report integration does not activate the update timer or resolve
existing update/SSH/repository failures.

### Register additional SSH targets and mandatory coverage

Use `scripts/register_system_update_hosts.py --config CONFIG --ssh-user USER
--host alias=host.example.invalid --require-host alias` to register explicitly
identified targets. The helper writes a private inventory overlay next to the
config, adds it to the configured inventories, and starts new host policies in
audit mode. Existing aliases with conflicting SSH settings are refused. Existing
policies are preserved. Configuration and any prior overlay are backed up before
changes. Repeating the same registration makes no changes. The helper does not
connect to or install anything on the new targets.

`required_hosts` is an explicit list of inventory aliases whose coverage must be
visible. A missing alias is a `FAILED / REQUIRED_HOST_MISSING_FROM_INVENTORY` row
in the email and JSON report, and defers all security installations while the
reachable inventory is still audited. Registering a target proves neither SSH
reachability nor that the target is patched. Audit and review service/backup
policies before promoting any new host to security mode.

The runner selects the `bergen_update_diagnostic` stdout callback for each host.
It captures fixed error categories and allowlisted task names even when a role
rescues the original error, and includes them in the text, HTML and JSON report.
Connection failures are classified separately (DNS, host keys, authentication,
timeout, refusal or routing). Known APT refusal codes, DNF metadata verification,
Python and become failures are distinguished. Raw module messages, exception
text, connection endpoints and invocation arguments are never copied into this
diagnostic frame. Tasks marked `no_log` emit only `ERROR_DETAILS_REDACTED`.
Unknown errors remain explicitly unclassified; no success or root cause is
inferred from missing diagnostics. This does not relax any installation gates.

### Repair of the observed subscription-less PVE 9 source layout

`scripts/repair_proxmox_update_sources.py --config CONFIG` targets only the exact
inventory alias `venombox`. It requires PVE 9, subscription status `notfound`, the
reviewed single-stanza Trixie source files and the existing Proxmox archive key.
It disables `pve-enterprise.sources`, preserves the active PVE no-subscription
source and switches the existing Ceph Squid source to the public no-subscription
channel **without changing Ceph release**. It refuses unexpected source options,
signing keys, releases, duplicate fields and disabled public sources.

Before writing, it backs up the changed files under
`/var/backups/bergen-platform/update-sources-*` on the target. A failed strict
APT metadata refresh restores those source files; the report records rollback
failure separately. No package installation, restart, reboot or crypto-policy
change is performed. PVE/Ceph package maintenance and Ceph release lifecycle
review remain separate from the Debian security-only update role.

The controller keeps a private Ansible log, JSON evidence and a text report under
the configured state directory. A dedicated HTML/plaintext change email with JSON
evidence is sent through the existing SMTP configuration even on repair failure.
Terminal output is limited to a start line and the result/delivery status. An
unknown remote result requires local log review before deciding on further work.
The command returns nonzero on remote failure even if Ansible rescued the task.
The Python payload is transported as base64 so that Ansible cannot interpret
Jinja-looking text inside its source. A real local Ansible regression test passes
the full script through the generated play, forces a refusal before source reads
or writes, and verifies that failed-remote JSON evidence reaches the controller.
Missing evidence is reported as `ANSIBLE_RESULT_MISSING` with the Ansible exit
code rather than only a generic local `FileNotFoundError`.

```sh
python3 scripts/repair_proxmox_update_sources.py \
  --config "$HOME/.config/bergen-updates/config.json"
```

This repairs only this observed repository failure; it does not establish a
successful inventory-wide audit or activate daily timers.

```sh
python -m unittest discover -s tests -p test_system_updates.py -v
ansible-playbook --syntax-check ansible/playbooks/system-updates.yml
ansible-playbook --syntax-check ansible/playbooks/install-system-update-scheduler.yml
```

Offline tests cover security origin filtering, holds, no downgrade, package
changes, fail-stop behavior with continued reporting, unreachable hosts,
credential omission, HTML escaping, TLS failure and independent watchdog alerts.
They do not replace a first live audit, canary update, second idempotent run,
application checks and mailbox receipt verification.
