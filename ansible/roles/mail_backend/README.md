# mail_backend

Configures an internal Postfix/Dovecot mail backend on Debian 13. The role is
designed to replace a mailbox server behind an existing public SMTP gateway.

## Responsibility

The role provides:

- trusted inbound SMTP from an existing edge gateway;
- authenticated SMTP submission on ports 587 and 465;
- Dovecot IMAPS and LMTP delivery;
- LDAP password authentication for all matching directory accounts;
- mailbox authorization restricted to an LDAP `Mailuser` group filter;
- create-only daily mailbox provisioning;
- multiple equivalent identity domains;
- explicit recipient aliases and separate Send-as ownership;
- relay of all outgoing mail to the existing edge gateway.

The role intentionally does **not** provide:

- a public MX or edge spam filter;
- DKIM signing, public reputation or DNS policy;
- LDAP account lifecycle management;
- webmail;
- automatic migration or deletion of existing mailboxes;
- automatic firewall changes.

## Identity model

LDAP remains the source of credentials. A successful LDAP `passdb` lookup is
sufficient for SMTP AUTH, so a technical account can submit mail without
owning a mailbox. Dovecot `userdb` and the provisioning query use the separate
`mail_backend_ldap_mailuser_filter`; only matching users can use IMAP or receive
LMTP delivery.

The role never deletes mail data when a user leaves the group or LDAP.

## Address model

`mail_backend_identity_domains` defines domains on which an authenticated LDAP
login may use its own local part. For example, login `alice` may submit as
`alice@example.net` and `alice@example.org` when both domains are listed. All
non-primary identity domains are recipient aliases to the primary domain.

Addresses with another local part are declared explicitly:

```yaml
mail_backend_aliases:
  - address: info@example.net
    recipients:
      - alice@example.net
      - bob@example.net
    send_as:
      - alice
```

Recipient membership and Send-as ownership are deliberately independent.

## Required variables

At minimum configure:

- `mail_backend_hostname`
- `mail_backend_primary_domain`
- `mail_backend_identity_domains`
- `mail_backend_postmaster_address`
- `mail_backend_relay_host`
- `mail_backend_trusted_networks`
- all `mail_backend_ldap_*` connection and filter variables

Start from `ansible/group_vars/all/bergen-mail.yml.example`. Site-specific
values belong in the ignored `bergen-mail.yml`; secrets belong in Ansible
Vault.

LDAP searches may use either an anonymous bind or an application account. For
anonymous search, leave both `mail_backend_ldap_bind_dn` and
`mail_backend_ldap_bind_password` empty. For an application bind, configure
both values together. SMTP/IMAP password verification still binds as the
authenticating LDAP user.

## Generated files

- `/etc/postfix/main.cf`
- `/etc/postfix/master.cf`
- `/etc/postfix/ldap_mailboxes.cf`
- `/etc/postfix/virtual_aliases*`
- `/etc/postfix/sender_login_aliases*`
- `/etc/postfix/ldap_domain_aliases.cf`
- `/etc/postfix/sender_login_domains.pcre`
- `/etc/dovecot/dovecot.conf`
- `/etc/bergen-platform/mailbox-provision.json`
- `/usr/local/sbin/bergen-mailbox-provision`
- `/etc/systemd/system/bergen-mailbox-provision.*`

## Services

| Port | Service | Expected source |
|---:|---|---|
| 25 | trusted SMTP | edge gateway private/WireGuard address only |
| 465 | implicit-TLS submission | explicitly allowed client VLANs |
| 587 | STARTTLS submission | explicitly allowed client VLANs |
| 993 | IMAPS | user/client networks |

Network policy must be enforced by Proxmox and/or the LXC firewall. Do not
publish the backend's port 25 directly to the internet.

## Deployment

```bash
cp ansible/group_vars/all/bergen-mail.yml.example \
  ansible/group_vars/all/bergen-mail.yml

cp ansible/inventory.local.yml.example \
  ansible/inventory.local.yml

ansible-playbook ansible/playbooks/deploy-mail-backend.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e @ansible/group_vars/all/bergen-mail.yml \
  --ask-vault-pass
```

Deploy the role to an existing container with:

```bash
ansible-playbook ansible/playbooks/bootstrap-mail-backend.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e @ansible/group_vars/all/bergen-mail.yml \
  --ask-vault-pass
```

The discovered address is persisted only in the ignored
`ansible/inventory.local.yml`. The tracked `ansible/inventory.yml` keeps an
empty `mail_backend_nodes` group and therefore contains no site-specific mail
backend address.

## Validation

The role fails before changes when required topology, LDAP filters or alias
ownership are incomplete. After configuration it runs:

- `postfix check`
- `doveconf -n`
- listener checks for IMAPS and enabled submission ports
- one initial create-only LDAP mailbox provisioning pass

Before cutover, additionally verify LDAP authentication, one Mailuser, one
non-Mailuser technical sender, every alias and gateway relay delivery.

## Security boundary

Postfix `smtpd_sender_login_maps` protects the SMTP envelope sender. It does not
compare the authenticated login with the RFC 5322 `From:` header. A production
cutover must either add a suitable policy/Milter check or document and accept
that limitation. The public gateway must not be treated as the enforcement
point because it no longer sees the original authenticated client.
