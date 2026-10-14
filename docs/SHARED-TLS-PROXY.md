# Shared certificate distribution: optional internal Nginx target

The existing Certbot wildcard source, mail TLS sync script, mail target
verification, mail activation helper and enabled systemd timer stay unchanged
when no new command-line option is provided.

This development stage adds only an *opt-in read-only* internal proxy target
audit to the existing **scripts/mail_tls_sync.py** entry point. It does not
create a second persistent certificate synchronizer on the controller or in
the proxy LXC. The prior experimental standalone first-installer is superseded.

## Verify unchanged Mail TLS behavior

    cd ~/bergen-platform
    .venv/bin/python3 scripts/mail_tls_sync.py \
      --config ansible/vars/mail-tls.local.yml

With the same source and unchanged mail certificate, output should continue
to show \`NO_CHANGE\` and successful IMAP/SMTP listener checks.

The existing mail-tls-sync.service and mail-tls-sync.timer do not supply the
optional arguments and **do not touch the proxy**. Their normal execution is
unaffected by this change.

## Inspect isolated proxy without transferring certificates

Use the same existing source configuration and strict SSH transport currently
used by the mail distributor. The additional proxy config and local inventory
must be the reviewed, git-ignored site-specific files.

    python -m unittest discover -s tests \
      -p 'test_shared_tls_proxy_audit.py' -v

    .venv/bin/python3 scripts/mail_tls_sync.py \
      --config ansible/vars/mail-tls.local.yml \
      --proxy-vars ansible/group_vars/all/bergen-proxy.yml

This first completes the original mail certificate and live listener checks,
then audits the isolated LXC through the verified PCT-mediated guest SSH
connection. In the new LXC, the expected result is:

    PROXY TLS: MISSING_EXPECTED_FIRST_INSTALL
    PROXY TLS: AUDIT_ONLY; no files transferred or services changed

Existing complete TLS files are checked for protected ownership/mode,
certificate/key pairing, expiry and hostname coverage, then classified as
NO_CHANGE or ROTATION_CANDIDATE. A partial installation fails closed.

## Safety limits

- \`--proxy-vars\` combined with \`--apply\` is rejected **before** any SSH
  operation or certificate file read, to avoid implying proxy deployment.
- No private key content is fetched, copied or logged by the new adapter.
- Source SSH settings and mail Certbot lineage are reused unchanged.
- Isolated guest connectivity uses the reviewed Proxmox PCT SSH path.
- Neither first deployment nor automated Nginx certificate rotation is
  implemented in this stage.
- Existing mail Postfix/Dovecot activation and systemd timer stay unchanged.
- Nginx deployment still requires real backend, private ingress allowlist,
  DNS/WAN checks, certificate deployment, rollback and live HTTPS checks.

Next add a separately gated proxy activation adapter to this central
distributor, with secure streamed transfer, atomic cert/key activation,
Nginx syntax validation, TLS listener verification, and rollback. Review
initial install and later rotation as distinct scenarios.
