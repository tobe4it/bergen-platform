# Mail Backend

## Purpose

The Bergen Platform mail backend replaces a Synology mailbox server while
retaining the existing public SMTP gateway. It separates connection-level edge
policy from identity, submission and mailbox storage.

## Architecture

```text
Internet
   |
   v
Public edge gateway
   |  trusted SMTP over private transport/WireGuard
   v
bergen-mail LXC
   +-- Postfix inbound/aliases/submission
   +-- Dovecot LDAP auth/LMTP/IMAPS
   +-- /var/vmail mailbox data
   |
   +-- Synology/OpenLDAP directory
```

Outgoing messages take the reverse path through the public gateway. The edge
gateway remains responsible for public delivery, DKIM, reputation and its
queue. It does not need LDAP users or password hashes.

## Authorization rules

1. Every LDAP account matched by `mail_backend_ldap_passdb_filter` may
   authenticate to SMTP submission.
2. Only accounts matched by `mail_backend_ldap_userdb_filter` and the daily
   `Mailuser` provisioning filter own a mailbox and can use IMAP/LMTP.
3. Every LDAP login may use its own local part in each identity domain.
4. Custom aliases define recipient expansion and Send-as owners separately.
5. Mailbox provisioning creates missing mailboxes and never deletes data.

This permits dedicated Reolink/scanner/service LDAP identities without
mailboxes.

## LDAP schema adaptation

Synology LDAP and Synology Directory/AD can expose different account and group
attributes. The role therefore does not hard-code group semantics. Test and set
these filters for the actual directory:

- `mail_backend_ldap_passdb_filter`
- `mail_backend_ldap_userdb_filter`
- `mail_backend_ldap_mailuser_filter`
- `mail_backend_ldap_recipient_query_filter`

Do not cut over based only on an assumed `memberOf` implementation. Verify the
queries with `ldapsearch` and test both directory account types used at the
site.

## Alias migration

Synology Mail Server aliases are mail-server configuration, not automatically
LDAP objects. Export or inventory them before cutover and translate each one to
the declarative structure:

```yaml
mail_backend_aliases:
  - address: alias@example.net
    recipients:
      - destination@example.net
    send_as:
      - authorized-ldap-login
```

For distribution aliases, do not infer Send-as ownership from every recipient
unless that is the intended policy.

## Parallel migration plan

### 1. Inventory

- record all served and equivalent domains;
- export aliases and group membership;
- list active mailboxes and mailbox sizes;
- identify technical SMTP senders;
- document TLS names and gateway transport;
- take a restorable Synology mail backup.

### 2. Deploy without traffic

- copy both `bergen-mail.yml.example` and `inventory.local.yml.example` to
  their ignored destination files;
- create `bergen-mail` from the local variables while passing the public and
  local inventory sources to Ansible;
- verify both LDAP directory types and the `Mailuser` group filter;
- run `bergen-mailbox-provision.service` manually;
- test IMAPS and SMTP AUTH with a temporary certificate/trust setup;
- keep public relay and DNS unchanged.

### 3. Test policy

- Mailuser: SMTP AUTH, IMAP and delivery succeed;
- non-Mailuser technical account: SMTP AUTH succeeds, IMAP and delivery fail;
- own addresses in every identity domain are allowed;
- declared aliases are allowed only for their `send_as` owners;
- an unowned alias and an arbitrary local sender are rejected;
- relay delivery through the edge gateway succeeds.

### 4. Copy mail

Use IMAP-aware migration (`doveadm backup`/`imapsync`) or a separately verified
Maildir conversion. Preserve dates, flags, folders and Sieve rules. Run an
initial bulk copy followed by an incremental copy immediately before cutover.

### 5. Cut over

- stop changes to aliases on Synology;
- run the final incremental copy;
- change the gateway's internal relay target to `bergen-mail`;
- change IMAP/submission DNS or client configuration;
- monitor Postfix queue, Dovecot authentication and delivery logs.

### 6. Rollback window

Keep Synology read-only and do not remove its mail data until delivery, aliases,
submission and backups have been verified for an agreed observation period.

## Backup

Back up at least:

- the complete Proxmox LXC;
- `/var/vmail` mailbox content;
- Ansible/Vault configuration;
- TLS material where it is not reproducibly issued;
- an alias/configuration export at each significant change.

The site configuration in `ansible/group_vars/all/bergen-mail.yml`, Vault file
and effective address in `ansible/inventory.local.yml` are ignored by Git.
Back them up separately from the public repository. The generated operational
configuration also exists inside the LXC and is covered by a complete LXC
backup.

Mailbox deletion is intentionally outside the role. Define retention and an
archive workflow before automating deprovisioning.

## Known initial boundary

Envelope Send-as authorization is implemented. Visible `From:` header ownership
needs an additional policy or Milter check before the platform can claim strict
anti-spoofing for authenticated clients. Webmail is also a separate component;
this role replaces the mail server, not Mail Station's browser interface.
