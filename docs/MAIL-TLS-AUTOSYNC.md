# Automated distribution of a renewed mail wildcard certificate

The controller utility reuses the Git-ignored local YAML from the read-only
preflight. No actual hostnames, DNS zones, Certbot lineages, credentials or key
material are committed. This utility distributes renewed certificates only:
it does not renew Let's Encrypt certificates itself.

## Preconditions

The controller requires its Python virtual environment with PyYAML and ssh.
Both SSH peer host keys must already be independently verified and pinned.
The source user requires noninteractive sudo -n privileges to read the Certbot
certificate/key and inspect them with OpenSSL. The target requires verified
noninteractive root SSH access. Restrict sudo rules on the source, never
disable host-key verification and never enable agent forwarding.

The installed mail certificate and key must already form a valid pair. Missing
or mismatched live files require manual repair before automatic deployment.

The real ignored YAML, ansible/vars/mail-tls.local.yml, must be mode 0600.
It uses the same variables as the existing Ansible preflight. Optional YAML
entries are:

    mail_tls_target_ssh_address: CHANGE_ME_SSH_ALIAS
    mail_tls_target_ssh_user: root
    mail_tls_check_ports: [993, 587, 465]

The target SSH address defaults to mail_tls_target_inventory_host and its
SSH user defaults to root. Only include ports that actually run on the target.

## First run: no changes

From the repository root on the controller:

    chmod 600 ansible/vars/mail-tls.local.yml
    python3 -m pytest -q tests/test_mail_tls_sync.py
    bash -n scripts/mail_tls_remote_activate.sh

    .venv/bin/python3 scripts/mail_tls_sync.py \
      --config ansible/vars/mail-tls.local.yml

The first invocation is read-only. If the source and target already have
identical certificate fingerprints, it verifies the actual TLS listeners and
reports NO_CHANGE without copying any file or restarting any service. When
the source differs, the program reports ROTATE but does not change anything.
After manual review, an explicit production rotation is:

    .venv/bin/python3 scripts/mail_tls_sync.py \
      --config ansible/vars/mail-tls.local.yml --apply

The source check requires an unexpired certificate with at least 30 days
validity left, matching wildcard SAN, expected hostname, and matching
certificate/key public keys. The target checks the effective Postfix/Dovecot
TLS settings and the installed certificate/key pairing. A certificate
downgrade to an earlier expiry is rejected.

For a real rotation, both files travel over verified SSH as an encrypted
pipe; no private-key file is created on the controller. The target validates
the staged certificate, private key, CA chain and destination permissions.
Before changing live files it creates a restricted rollback copy. Postfix
and Dovecot are stopped briefly, the new pair activated and checked over
the configured TLS service ports. Detected activation errors trigger a
best-effort rollback. Abrupt power loss or SIGKILL cannot be rolled back.

Staging is removed after the attempt if reachable. Rollback copies are
deliberately retained and require separately reviewed cleanup.

## Opt-in systemd user timer

Install the unit examples locally on the controller only after a successful
read-only run and confirmation that both SSH access paths are noninteractive.

    mkdir -p ~/.config/systemd/user
    cp systemd/user/mail-tls-sync.service.example \
       ~/.config/systemd/user/mail-tls-sync.service
    cp systemd/user/mail-tls-sync.timer.example \
       ~/.config/systemd/user/mail-tls-sync.timer
    systemctl --user daemon-reload
    systemctl --user start mail-tls-sync.service
    systemctl --user status mail-tls-sync.service
    systemctl --user enable --now mail-tls-sync.timer
    systemctl --user list-timers mail-tls-sync.timer

The sample unit expects the repository at %h/bergen-platform and the venv
inside it. Adapt only the untracked installed systemd unit if needed. A
persistent user timer after logout may require enabling systemd lingering
for the controller account.

The timer checks daily around 04:15, with up to 30 minutes randomized delay.
Failures produce a nonzero unit result and a journal message. Inspect via:

    journalctl --user -u mail-tls-sync.service --since '7 days ago'
    systemctl --user --failed

Failed units are NOT automatically notifications. Connect failures to the
existing syslog/monitoring system if alert delivery is required.

Separately ensure that source Certbot DNS-01 certificate renewal can run
without manual intervention, or renew the source before the 30-day threshold.
