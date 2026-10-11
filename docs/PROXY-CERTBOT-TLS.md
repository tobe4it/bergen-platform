# Reuse the existing mail Certbot wildcard for internal Nginx

This module **reuses** the same currently operating Certbot source and
wildcard certificate that feed the mail TLS automation. It neither requests
another certificate nor changes source renewal hooks.

The read-only audit is deliberately independent of the Mail TLS distributor.
It takes existing local source settings from
\`ansible/vars/mail-tls.local.yml\` and proxy site/target settings from
\`ansible/group_vars/all/bergen-proxy.yml\`. Both files are git-ignored.
No actual hostnames, IPs, account data or certificate keys belong in Git.

## Verify source and target without any key transfer

From repository root on the controller, first ensure that the deployed
\`reverse_proxy_nodes\` inventory points to the reviewed LXC with an existing
PCT-mediated SSH transport and a verified guest SSH fingerprint.

\`\`\`sh
ansible-playbook \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/preflight-proxy-certbot-tls.yml \
  -e @ansible/vars/mail-tls.local.yml \
  -e @ansible/group_vars/all/bergen-proxy.yml \
  --syntax-check --ask-vault-pass

ansible-playbook \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/preflight-proxy-certbot-tls.yml \
  -e @ansible/vars/mail-tls.local.yml \
  -e @ansible/group_vars/all/bergen-proxy.yml \
  --check --ask-vault-pass
\`\`\`

The source must provide a noninteractive, already trusted SSH path and
privileged permission to inspect the root-owned Certbot key. The preflight
does not retrieve the key; it derives a public-key digest remotely and
compares it with the certificate-derived digest.

A successful SOURCE_VERIFIED result establishes SAN/hostname coverage,
30-day validity and a matching certificate/key pair at the existing
Certbot source. The target state will be
MISSING_EXPECTED_FIRST_INSTALL on a fresh LXC; this is expected and is
not a failure. It is not authorization to install certificates or Nginx.

## Follow-on distribution design (not implemented by this audit)

- Send a verified fullchain and key over pinned SSH from the Certbot source
  through controller-managed pipes straight into a restricted temporary
  directory on the target, using the already verified PCT SSH proxy.
  No persistent private-key copy on the controller; never emit key contents
  into Ansible logs or files in this repository.
- Validate source identity, target VMID and certificate/key before activation;
  validate CA chain, key ownership/mode and certificate expiration.
- If Nginx is running, validate its configuration, switch the certificate
  with safe rollback and reload only after verification. Initial installation
  must not assume a running Nginx service.
- Use a separate explicit \`--apply\` approval and staged tests.
- Renewal propagation should be triggered after source issuance and monitored;
  source Certbot itself remains unchanged.

The existing mail implementation in
\`scripts/mail_tls_sync.py\` and
\`scripts/mail_tls_remote_activate.sh\` offers transport and rollback patterns
but cannot be used unchanged: it verifies Postfix/Dovecot configuration and
SMTP/IMAP ports rather than HTTPS, and assumes a preinstalled valid
target certificate. The first Nginx certificate installation is different.

For least privilege, consider service-specific certificates instead of
distributing one wildcard private key across multiple containers.
