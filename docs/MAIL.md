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

The backend keeps the gateway's hostname as its Postfix relay target and sets
`smtp_address_preference = ipv4`. With split DNS, the internal A record can
therefore select the gateway's private/WireGuard address even when its public
hostname also has an AAAA record.

## Current implementation checkpoint

The internal deployment stage was reached and verified on 2026-08-29 and is
released as Bergen Platform v0.6.0. This is a functional infrastructure
checkpoint, not yet the production cutover from the existing mailbox server.

| Component | State | Verification performed |
|---|---|---|
| Debian 13 LXC | Deployed | Container creation, inventory discovery and Ansible connectivity succeeded |
| Internal service DNS | Verified | Both internal DNS paths resolve the service FQDN to the LXC address |
| LDAP transport | Verified | LDAPS base search succeeded with certificate verification required |
| Dovecot configuration | Verified | Dovecot 2.4 configuration parses and the service starts |
| LDAP userdb | Verified | A `Mailuser` account resolves to the virtual UID/GID and Maildir paths |
| Mailbox provisioning | Verified | Initial create-only provisioning completed successfully |
| Postfix configuration | Verified | `postfix check` succeeds and the service starts |
| Runtime listeners | Verified | SMTP, submissions, submission and IMAPS listen on non-loopback IPv4 and IPv6 addresses |
| Relay selection | Configured | The gateway hostname is retained and outbound SMTP prefers its IPv4 address |
| Repeat bootstrap | Verified | A complete repeat bootstrap finished without failed tasks |

The deployed role deliberately separates facts proven by local service checks
from functions that still require end-to-end acceptance tests. A successful
Ansible run does not yet prove public delivery, client authentication, alias
policy, certificate trust or mailbox migration.

## Name and network model

The backend uses three different identities that must not be conflated:

| Identity | Purpose |
|---|---|
| LXC inventory name | Ansible and infrastructure management |
| Mail service FQDN | IMAPS/submission endpoint and TLS certificate name |
| Gateway FQDN | Single Postfix smart host for all outbound delivery |

Split DNS may resolve the mail service FQDN directly to the LXC internally and
to a public VPS later. Clients keep the same service name in both locations.
The gateway FQDN may likewise have a private/WireGuard A record internally and
public A/AAAA records externally.

Postfix is configured with `inet_protocols = all` so inbound listeners support
both address families. This is independent from
`smtp_address_preference = ipv4`, which applies to outbound Postfix SMTP client
connections and makes the private/WireGuard A record the preferred gateway
path.

Changing `inet_interfaces` requires a complete Postfix restart to activate new
non-loopback listeners. The role therefore validates the configuration and
restarts Postfix as one handler event. Runtime validation rejects listeners
that exist only on loopback.

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

Directory searches support either anonymous access or an application bind.
Leave both bind variables empty for anonymous search; configure both together
for an application bind. Password verification remains a user bind and does
not require password hashes on the mail server.

## Operations and validation

### Deploy or reconcile the existing LXC

```bash
ansible-playbook ansible/playbooks/bootstrap-mail-backend.yml \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  -e @ansible/group_vars/all/bergen-mail.yml \
  --ask-vault-pass
```

The role is declarative and repeatable. It validates generated Postfix and
Dovecot configuration before restarting either service.

### Inspect the effective configuration

Run these commands through Ansible or directly as root on the LXC:

```bash
postfix check
postconf -h myhostname
postconf -h relayhost
postconf -h smtp_address_preference
doveconf -n
```

Expected relay properties are one bracketed smart host, the configured gateway
port and IPv4 address preference. Do not use `postconf -n` or `doveconf -P` in
shared logs without first checking whether the output contains credentials.

### Verify listeners

```bash
ss -lntp | grep -E ':(25|465|587|993)\b'
```

Enabled listeners must bind to the intended non-loopback addresses. Merely
seeing `127.0.0.1:587` is not sufficient for LAN clients.

### Verify LDAP-backed mailbox identity

```bash
doveadm user LDAP_LOGIN
```

For a `Mailuser`, the result must contain the virtual UID/GID, home directory
and Maildir path. `doveadm user` does not query a separate Dovecot user list;
it exercises Dovecot's configured LDAP userdb directly.

For temporary authentication debugging add this to the generated Dovecot
configuration, restart Dovecot, reproduce the lookup and remove it again:

```text
log_debug = category=auth
```

Dovecot hides passwords at this debug level. Do not enable
`auth_debug_passwords` in production or in captured support output.

### Provision and inspect mailboxes

```bash
systemctl start bergen-mailbox-provision.service
systemctl status bergen-mailbox-provision.service --no-pager
systemctl list-timers bergen-mailbox-provision.timer
```

Provisioning is create-only. Removing an LDAP user or `Mailuser` membership
never removes existing mail data.

### Inspect queues and service logs

```bash
mailq
journalctl -u postfix -n 100 --no-pager
journalctl -u dovecot -n 100 --no-pager
journalctl -u bergen-mailbox-provision.service -n 100 --no-pager
```

The public gateway remains the authoritative location for internet-facing SMTP
connection, reputation, policy and queued-delivery diagnostics.

### Verify TLS before client rollout

```bash
openssl s_client -connect MAIL_SERVICE_FQDN:993 \
  -servername MAIL_SERVICE_FQDN -verify_return_error

openssl s_client -starttls smtp -connect MAIL_SERVICE_FQDN:587 \
  -servername MAIL_SERVICE_FQDN -verify_return_error
```

Both tests must present a trusted certificate containing the exact service
FQDN. A self-signed certificate is acceptable only for the isolated bootstrap
stage.

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

## Open points and acceptance criteria

The following items remain open after the internal deployment checkpoint. They
are ordered approximately by dependency and cutover risk.

### 1. Source-controlled rollout

- Pull the current feature branch on the controller without overwriting the
  ignored site configuration.
- Run the bootstrap from the pulled role and confirm a clean result.
- Review and merge the feature branch only after the remaining acceptance tests
  below are recorded.

Acceptance: controller and GitHub branch contain the same role version and a
repeat bootstrap reports no failed tasks.

### 2. TLS lifecycle

- Issue a publicly trusted certificate for the mail service FQDN, preferably
  with DNS-01 so no temporary public web listener is required.
- Automate renewal and a validated Postfix/Dovecot restart or reload path.
- Alert before expiry and test the full presented chain from Apple clients.

Acceptance: IMAPS and STARTTLS verification succeeds without a locally
installed exception and renewal is reproducible.

### 3. Firewall and routing policy

- Allow backend port 25 only from the gateway's private/WireGuard source.
- Define the internal VLANs allowed to reach 465, 587 and 993.
- Decide and document the later VPS forwarding/proxy design for external client
  access.
- Restrict outbound TCP/25 to the intended gateway path if bypass prevention is
  required.
- Test IPv4 and IPv6 rules independently.

Acceptance: unauthorized sources cannot connect, while every intended client
network and the gateway can reach only its required ports.

### 4. Gateway integration

- Verify that the backend can relay outbound mail to the gateway over the
  private/WireGuard A record.
- Configure and test gateway delivery to the backend.
- Confirm gateway queueing while the backend or tunnel is unavailable.
- Confirm PTR/rDNS, SPF, DKIM, DMARC and outbound TLS behavior at the public
  gateway.

Acceptance: an external round trip succeeds and a simulated backend outage
queues rather than loses inbound messages.

### 5. Authentication and authorization matrix

Test at least these cases explicitly:

| Test identity | SMTP AUTH | IMAP | Local delivery |
|---|---:|---:|---:|
| `Mailuser` account | Allow | Allow | Allow |
| LDAP technical account without mailbox | Allow | Deny | Deny |
| Unknown or disabled identity | Deny | Deny | Deny |

Acceptance: all outcomes match the table using real clients or protocol-level
tests, not only LDAP searches.

### 6. Address, alias and Send-as policy

- Inventory every existing mailbox domain and Synology alias.
- Declare recipient expansions and Send-as owners independently.
- Test own-address sending in every identity domain.
- Reject unowned aliases and arbitrary envelope senders.
- Add a policy service or Milter for RFC 5322 `From:` ownership, or explicitly
  accept and document the remaining spoofing boundary.

Acceptance: a recorded test matrix covers every migrated alias and both allowed
and rejected Send-as cases.

### 7. External client access and abuse protection

- Keep access internal for the first stage as currently intended.
- Before public exposure, select either routed forwarding with preserved source
  addresses or a TCP proxy with correctly restricted PROXY protocol listeners.
- Add Fail2ban or equivalent rate limiting where the real client address is
  visible.
- Verify that internal clients cannot forge PROXY headers.

Acceptance: public brute-force attempts can be attributed and blocked per
client address without exposing administrative services.

### 8. Mail data migration

- Inventory mailbox sizes, folders, flags, dates, subscriptions and Sieve
  rules.
- Perform an initial test migration and compare counts and representative
  messages.
- Plan bulk and final incremental synchronization.
- Keep the Synology mailbox source read-only throughout the rollback window.

Acceptance: source and target counts and metadata match within documented
exceptions, and rollback remains possible.

### 9. Backup, restore and retention

- Add the LXC and `/var/vmail` to the backup plan.
- Back up ignored Ansible/Vault site configuration and certificate material by
  a separate protected mechanism.
- Perform a restore test into an isolated target.
- Define retention, archive and deliberate mailbox deletion procedures.

Acceptance: a timed restore test recovers configuration and a representative
mailbox without depending on the running source LXC.

### 10. Monitoring and operational readiness

- Monitor Postfix queue depth, rejected mail, Dovecot authentication failures,
  disk usage, certificate expiry and provisioning timer failures.
- Forward relevant logs to the central logging platform.
- Define alert thresholds and a short incident/rollback runbook.
- Add automated role syntax/idempotence tests where practical.

Acceptance: simulated queue growth, failed authentication, low disk space and a
failed provisioning job each produce an actionable signal.
