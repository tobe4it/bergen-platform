# Mail TLS and Certbot operations

> Operational runbook for the public mail gateway and the separate internal
> mail backend. Verified production checkpoint: **2026-10-11**.
>
> **Confidentiality:** Real FQDNs, public/private addresses, DNS provider record
> IDs, Certbot lineage identifiers, account email addresses, private keys, API
> credentials and recovery-directory names are **site-local**. They must not
> appear in the public repository, issues, commits or copied terminal logs.
> All capitalized identifiers below are placeholders, not production values.

## 1. Scope, ownership and trust boundaries

The public SMTP gateway (source host) owns internet-facing Postfix, Nginx,
Certbot, DNS-01/HTTP-01 authorization, public MTA-STS and their renewal hooks.
The Ansible controller orchestrates the selected certificate synchronization
to the internal `bergen-mail` LXC. The internal Postfix/Dovecot backend owns
authenticated submission and IMAPS and is deliberately distinct from the
internet-facing gateway.

```text
Internet / Let's Encrypt
       |
       +--- HTTP-01 / DNS-01 ---> public mail gateway
       |                         +-- Certbot + renewal timer
       |                         +-- Postfix RSA/ECDSA
       |                         +-- Nginx HTTPS + MTA-STS
       |                         +-- lineage-scoped deploy hooks
       |
       +--- SMTP ---> public mail gateway
                          |
                          +-- private mail relay ---> bergen-mail LXC
                                                   Postfix + Dovecot
                                                 ^        |
                                                 |   IMAPS/submission
                               selected wildcard TLS certificate
                                                 |
                                         Ansible controller
                                         certificate sync timer
```

Do not conflate `bp-controller`, the public MX host, and `bergen-mail`.
A successful `certbot-renew.service` on the MX host does not demonstrate that
the controller-to-backend sync has run, and a valid certificate on disk does
not prove that Nginx/Postfix/Dovecot is serving the new certificate.

This runbook covers **the existing configuration and verified repairs**. It
does not assert that the entire public MX host can be recreated from scratch by
the two scoped Ansible playbooks. Mailbox migration, external-client exposure,
LDAP policy and gateway routing still have independent acceptance criteria in
[MAIL.md](MAIL.md).

## 2. Certificate inventory and methods

| Purpose | Certificate / ACME method | Consumer | Ownership |
|---|---|---|---|
| Public SMTP, RSA | Separate RSA lineage, HTTP-01 webroot | Postfix | MX |
| Public SMTP, ECDSA | Separate ECDSA lineage, HTTP-01 webroot | Postfix | MX |
| Gateway web/TLS and synchronized backend certificate | Apex + one-level wildcard, DNS-01 with selfHOST auth/cleanup hooks | Nginx; selected internal services via certificate sync | MX issues; controller copies |
| MTA-STS policy HTTPS | Exact-name certificate, HTTP-01 webroot | Nginx | MX |
| Other legacy/site-specific HTTPS certificates | Individually owned; do **not** assume identical validation | Nginx or other services | Verify per lineage |

The wildcard certificate covers the apex when the apex name is explicitly
included, plus one subdomain level. A wildcard such as
`*.example.invalid` does not cover `example.invalid` or
`deep.host.example.invalid`. A separate wildcard for nested service names
is **not** needed when one exact-name certificate suffices. Do not replace
working exact-name MTA-STS lineages with a broad wildcard without an
inventory and a validated benefit.

The RSA and ECDSA Postfix certificates remain separate. Verify the active
settings on the MX rather than assuming Certbot's certificate list describes
the live SMTP configuration:

```bash
sudo postconf -h smtpd_tls_cert_file
sudo postconf -h smtpd_tls_key_file
sudo postconf -h smtpd_tls_eccert_file
sudo postconf -h smtpd_tls_eckey_file
sudo postfix check
```

The private keys, `/etc/letsencrypt/live/` symlinks,
`/etc/letsencrypt/archive/`, `/etc/letsencrypt/renewal/` and DNS-01
credentials stay on the respective host. Never commit their contents.

## 3. Production checkpoint and evidence

The following reflects checks actually observed on **2026-10-11**, not a
promise about subsequent renewals:

| Check | Observed evidence | State |
|---|---|---|
| Gateway RSA/ECDSA | Scoped Certbot staging renewals had succeeded previously; production lineages valid in the latest global run | Verified for staging; not forced to renew in the final global run |
| Gateway apex/wildcard | Issued with persistent selfHOST DNS-01 hooks; staging renewal tested previously | Issuance/staging tested; next unattended rotation outstanding |
| Controller-to-backend | Daily certificate-sync timer and IMAPS 993 / submission 465,587 validation previously confirmed | Functional checkpoint; monitor future runs |
| MTA-STS HTTP-01 IPv4 | Test file returned the expected marker with HTTP 200 | PASS |
| MTA-STS HTTP-01 public IPv6 | After adding `listen [::]:80`, test file returned HTTP 200 | PASS |
| MTA-STS staging | Exact-name `certbot renew --cert-name ... --dry-run` | PASS |
| MTA-STS production | New cert issued and Nginx reloaded | PASS |
| MTA-STS HTTPS IPv4 and IPv6 | Both served the trusted renewed cert and policy | PASS |
| MTA-STS policy | HTTPS 200; STSv1 `enforce`, expected MX, seven-day `max_age` | PASS |
| MTA-STS deploy hook | Foreign lineage ignored; own lineage verified `nginx -t` and reloaded Nginx | Simulated invocation PASS |
| Ansible MTA-STS adoption | Four offline tests, syntax check, remote preflight `changed=0 failed=0` | PASS |
| Global Certbot timer run | Scheduled run completed successfully; **no certificates due; no renewal attempted** | PASS for scheduling/scan only |

At the checkpoint, **ten active renewal profiles** were processed by the
global Certbot scan, all skipped because not due. Seven obsolete or
non-local renewal profiles had been quarantined separately during cleanup;
their archives/certificates were not deleted. A successful no-op scan is
**not** an end-to-end test of the automatic renewal hooks.

Exact certificate dates, live domain names and quarantine locations belong in
a protected local operations record; the authoritative expiry is always
`openssl x509 -noout -dates` on the actual live certificate.

## 4. Deployment hook contract

Certbot executes deploy hooks when a certificate is successfully deployed.
These hooks must make **no changes for unrelated lineages**, and failures
for the selected lineage must produce a nonzero exit status. All hook paths
and real lineage names are supplied by site-local configuration.

| Hook | Trigger | Action | Negative behavior |
|---|---|---|---|
| Postfix reload | Exactly the configured RSA or ECDSA lineage | Check Postfix is active, then reload | Ignore unrelated lineage; fail if inactive/reload fails |
| Wildcard Nginx reload | Exactly the selected wildcard lineage | Check Nginx active, `nginx -t`, reload | Ignore unrelated lineage; fail on error |
| Exact-name MTA-STS Nginx reload | Exactly the named MTA-STS lineage | `nginx -t`, reload | Ignore unrelated lineage; fail on test/reload error |

The MTA-STS hook installed on the MX is deliberately minimal and must
remain limited to one lineage. Its semantic template is:

```sh
#!/bin/sh
set -eu
[ "${RENEWED_LINEAGE:-}" = "/etc/letsencrypt/live/EXACT_MTA_STS_LINEAGE" ] || exit 0
/usr/sbin/nginx -t
exec /usr/bin/systemctl reload nginx
```

Only the **exact** lineage is authorized; this is not a global Nginx reload
for every certificate. Do not change the separate Postfix or wildcard hooks
when working on MTA-STS, or use any deploy hook that suppresses failed reloads
with `|| true`.

The deploy-hook migration is managed by
[`mail-source-certbot-deploy-hooks.yml`](../ansible/playbooks/mail-source-certbot-deploy-hooks.yml).
It accepts only known previous or managed hook contents and runs read-only
unless `deploy_hook_apply=true` is **explicitly** supplied. Existing root-only
backups are deliberately not overwritten. Its offline verification is in
[`test_mail_source_certbot_deploy_hooks.py`](../tests/test_mail_source_certbot_deploy_hooks.py).

The selected MTA-STS vhost and exact-name hook are audited by
[`mail-source-mta-sts-vhost.yml`](../ansible/playbooks/mail-source-mta-sts-vhost.yml).
That playbook checks the two expected server names, certificate file references,
HTTP/HTTPS listeners and exact hook body. It only performs corrective writes
when `mail_mta_sts_apply=true` is explicitly requested; it takes a guarded
backup and attempts restoration after errors. It is primarily a **scoped
adoption/reconciliation playbook**, not a general Nginx provisioning role.
Tests: [`test_mail_source_mta_sts_vhost.py`](../tests/test_mail_source_mta_sts_vhost.py).

## 5. Ansible controller: safe audit and changes

All commands in this section run from the **Ansible controller**, in the
repository root. Real values are held in the Git-ignored
`ansible/vars/mail-tls.local.yml`, optionally using Ansible Vault.

Site-local variables read by the two playbooks:

```yaml
# Illustrative names only. The actual values belong to ignored local config.
mail_tls_source_address: SOURCE_ADDRESS
mail_tls_source_ssh_user: SSH_USER
mail_tls_source_cert_file: /etc/letsencrypt/live/WILDCARD_LINEAGE/fullchain.pem
mail_tls_postfix_rsa_lineage: RSA_LINEAGE
mail_tls_postfix_ecdsa_lineage: ECDSA_LINEAGE
mail_tls_postfix_hook_path: /etc/letsencrypt/renewal-hooks/deploy/POSTFIX_HOOK
mail_tls_nginx_hook_path: /etc/letsencrypt/renewal-hooks/deploy/WILDCARD_HOOK
mail_mta_sts_name: mta-sts.example.invalid
mail_mta_sts_conf_path: /etc/nginx/conf.d/mta-sts.example.invalid.conf
mail_mta_sts_hook_path: /etc/letsencrypt/renewal-hooks/deploy/MTA_STS_HOOK
```

First validate the repository files, then inspect the running host without
setting an apply flag:

```bash
git status --short
git check-ignore ansible/vars/mail-tls.local.yml
pytest -q tests/test_mail_source_certbot_deploy_hooks.py \
          tests/test_mail_source_mta_sts_vhost.py
ansible-playbook ansible/playbooks/mail-source-mta-sts-vhost.yml --syntax-check

ansible-playbook ansible/playbooks/mail-source-mta-sts-vhost.yml \
  --ask-vault-pass -e @ansible/vars/mail-tls.local.yml

ansible-playbook ansible/playbooks/mail-source-certbot-deploy-hooks.yml \
  --ask-vault-pass -e @ansible/vars/mail-tls.local.yml
```

Use the project's existing Vault identity/provider instead of
`--ask-vault-pass` when already configured. The localhost registration
tasks deliberately reject Ansible `--check`; **omitting the apply flag is
the read-only mode**. The expected MTA-STS report on the verified host is:

```text
http_ipv6_missing: false
https_ipv6_missing: false
deploy_hook_missing: false
explicit_apply: false
changed=0, failed=0
```

Do **not** use the apply flags merely to obtain a clean status report. An
unexpected guard failure requires inspecting the live vhost/contents,
checking branch and site-local variables, and reviewing the proposed scope.
Never bypass assertions with `--start-at-task` or ad hoc edits.

Only after explicit change approval and a successful read-only preflight
may either playbook be used with its respective `-e ..._apply=true` flag.
Do not run both applies together; evaluate impact and rollback after each.

## 6. MX host: periodic read-only health check

The following runs on the **public MX host**, not on the Ansible controller:

```bash
sudo systemctl list-timers --all certbot-renew.timer
sudo systemctl show certbot-renew.service \
  -p ActiveState -p Result -p ExecMainStatus
sudo journalctl -u certbot-renew.service -n 100 --no-pager

sudo certbot certificates
sudo nginx -t
sudo postfix check

sudo ls -l /etc/letsencrypt/renewal-hooks/deploy/
```

Read `/etc/sysconfig/certbot` and the effective
`systemctl cat certbot-renew.service` if the invocation differs from the
expected packaged service. Scheduled `certbot-renew.service` is a systemd
oneshot, so `inactive` by itself is normal after successful completion.
Its `Result` and journal are more informative. `failed` can represent an
earlier run; do not claim a new failure or clear/reset the status without
checking the timestamp and journal.

A good scheduled run may report `No renewals were attempted`: it proves
timer/service execution, **not** future successful ACME authorization, reload
or downstream certificate sync. Track expiry and issue an alert well before
the end of certificate validity.

### Check the actual HTTPS policy, both IP families

Use the real values from protected host records as shell variables on MX:

```bash
# On the MX; set these from the site-local inventory, not from this document.
FQDN=EXACT_MTA_STS_FQDN
MX_PUBLIC_IPV6=MX_PUBLIC_IPV6_ADDRESS

curl --noproxy '*' -fsS \
  --resolve "$FQDN:443:127.0.0.1" \
  "https://$FQDN/.well-known/mta-sts.txt"

curl --noproxy '*' -fsS \
  --resolve "$FQDN:443:[$MX_PUBLIC_IPV6]" \
  "https://$FQDN/.well-known/mta-sts.txt"
```

Never use `curl -k` as a success criterion. A browser/HTTPS check must
validate the certificate, hostname and chain. Where possible, test from an
**external network** as well; `--resolve` on the server confirms local
address/vhost behavior, not every firewall or routing path.

The policy must be the reviewed one: `version: STSv1`, expected mode,
expected MX identifier, and intended `max_age`. Do not change policy text
just to fix certificate renewal.

### Check issued and served expiry separately

```bash
# On MX, with an exact existing lineage:
LINEAGE=EXACT_MTA_STS_LINEAGE
sudo openssl x509 \
  -in "/etc/letsencrypt/live/$LINEAGE/fullchain.pem" \
  -noout -dates -ext subjectAltName
```

Compare this certificate to the one presented by the real HTTPS listener
through `openssl s_client -connect HOST:443 -servername HOST`, and do not
mistake an expired old Nginx backup for an active vhost. On the backend,
independently validate IMAPS 993 and submission 587/465 with SNI and chain
verification after certificate synchronization.

## 7. Exact-name MTA-STS HTTP-01 and IPv6 failure recovery

**Observed failure mode:** the MTA-STS FQDN had an A and AAAA record pointing
to the MX, but its Nginx server blocks used only `listen 80;` and
`listen 443 ssl http2;`. Other Nginx virtual hosts listened on `[::]:80`
and `[::]:443`. Let's Encrypt's HTTP-01 request to the public IPv6
address therefore reached an unrelated vhost and returned HTTP 404. The
initial loopback test against `::1` returned HTTP 403 because a separate
vhost explicitly listened on `[::1]:80`: it was **not** a valid test of the
public IPv6 virtual host.

**Verified repair** on the selected two Nginx server blocks:

```nginx
# HTTP server, alongside the existing IPv4 listener:
listen 80;
listen [::]:80;

# HTTPS server, alongside the existing IPv4 listener:
listen 443 ssl http2;
listen [::]:443 ssl http2;
```

No global `nginx.conf`, unrelated vhost, DNS, SELinux, Postfix, Certbot
renewal parameters or system-wide crypto policy needed to change. Confirm
`nginx -t` **before** each reload; verify the running listener after reload.

HTTP-01 uses `authenticator=webroot`, an explicit site-local webroot, and
`location ^~ /.well-known/acme-challenge/` with `try_files $uri =404`.
A file may exist and have correct UNIX permissions but still fail from
a wrong vhost or SELinux context. For an authorization test:

1. Confirm the configured webroot and Nginx `root` are identical, both A and
   AAAA resolve to the intended host, and challenge files have an Nginx-readable
   `httpd_sys_content_t` label where SELinux is enforcing.
2. Create a **temporary, non-hidden** file inside the existing challenge
   directory, e.g. `acme-probe.XXXXXXXX`; use `0644` and record its actual
   content/SELinux label. Remove it afterward.
3. Fetch that file using `curl --resolve` separately via
   `127.0.0.1` **and the public IPv6 address**; require HTTP 200 **and an
   exact body match** for both. Testing `::1` alone is insufficient when
   `[::1]:80` has its own listener.
4. Then run an **exact-lineage staging dry-run**; do not infer public
   reachability only from local HTTP tests.

```bash
# Run on the MX only. Never omit --cert-name in this recovery procedure.
LINEAGE=EXACT_MTA_STS_LINEAGE
sudo certbot renew --cert-name "$LINEAGE" \
  --dry-run --no-random-sleep-on-renew
```

Only after a successful staging run and explicit production authorization,
perform the **same exact-lineage** renewal without `--dry-run` and validate
certificate dates, Nginx reload and HTTPS on **both** address families.
If an automatic deploy hook did not run, a guarded
`sudo nginx -t && sudo systemctl reload nginx` is appropriate after
successful issuance.

The earlier failure was **not** established to be SELinux-related: directories
and the normal test file had `httpd_sys_content_t`; no relevant AVC was
observed. The first temporary file began with a dot and produced HTTP 403,
so it was not representative of an ACME token file.

## 8. Quarantine of unusable renewal profiles

Certbot automatically scans `/etc/letsencrypt/renewal/*.conf`. Old broken,
unused, expired mixed-domain or externally hosted lineages can repeatedly
fail global renewal even when active mail certificates work. **Quarantine**
means moving *only the individual approved renewal `.conf`* outside that
directory into a root-only recovery folder.

At the verified checkpoint, seven unneeded/non-local profiles had been
quarantined after individually assessing DNS, current consumers and use.
This included duplicate MX identities, an obsolete policy certificate,
a mixed-domain legacy certificate and one service hosted elsewhere. Do not
treat all existing certificates as candidates for quarantine.

Before moving any additional profile:

1. Verify **actual** ownership and DNS targets, including AAAA; verify
   that relevant Nginx/Postfix consumers and deploy hooks do not require it.
2. Inspect its renewal settings and check for any running Certbot process.
3. Obtain explicit approval for **that exact profile**.
4. Back up/quarantine only its renewal configuration with a unique root-only
   directory; do not delete `live/`, `archive/` or private keys.
5. Confirm the profile is absent from `renewal/`, retain the recovery path
   in a protected local operations record, and check the next scheduled run.
6. To restore, first verify renewed ownership/ACME method, then move only
   the reviewed profile back after checking for collisions and active
   Certbot processes. Test it in staging before enabling unattended renewal.

`certbot certificates` may still list certificates left in
`/etc/letsencrypt/live/` after their `.conf` has been quarantined.
That does **not** mean the profile remains eligible for automatic renewal.

The historical expired policy certificate was also referenced by an
obsolete **duplicate Nginx server block**. That old vhost was retired only
after confirming the replacement served an identical MTA-STS policy and a
valid certificate; its config was backed up outside Nginx's loaded config
directory. An Nginx reload and `nginx -T` confirmed the removal of the
conflicting server name. Do not casually restore that old vhost.

## 9. Other operational safeguards

### DNS-01 and selfHOST

The selected apex/wildcard lineage uses persistent selfHOST DNS-01
authentication and cleanup hooks. Renewal does not require a public
HTTP-01 route for this lineage. Preserve provider secrets only in
protected host/Vault configuration; never print token values, challenge
credentials or DNS record identifiers in shared logs. Validate the
lineage-specific staging renewal without changing unrelated certificates.
DNS propagation and provider authorization are distinct failure modes
from MTA-STS HTTP-01 routing.

### Crypto policy and legacy automation

A previous legacy root cron job attempted certificate maintenance via an
old external Ansible playbook and included a temporary global crypto-policy
downgrade. That **monthly legacy cron entry was disabled**. Do not
re-enable it or run the old playbook as a workaround for HTTP-01/HTTPS
errors. The separate existing nightly crypto-policy task was not
changed in this project. Any global policy change requires independent
review and approval. The current certificate lifecycle relies on the
supported Certbot timer and strictly scoped deploy hooks, not temporary
global TLS policy changes.

### Backup and recovery ownership

Existing live backups of the affected vhosts/hooks and quarantined renewal
profiles are on the **MX source**, root-restricted, not in this Git
repository. The Ansible playbook also has dedicated on-host backup paths
for future *approved* changes. Review these backups before attempting
automatic reconciliation; never overwrite prior safety evidence.
Keep an encrypted/offline copy of site-local Ansible variables, Vault data,
DNS provider configuration and server/ACME account recovery instructions.
Do not commit backups, private certificates or secret-enriched logs.

## 10. Operator response matrix

| Symptom | Verify first | Action boundary |
|---|---|---|
| `certbot-renew.service` is `failed` | Timestamp, `journalctl`, active vs obsolete profiles | Do not run unscoped `certbot renew`; isolate exact failing lineage |
| HTTP-01 fails with public IPv6 404 | DNS AAAA, Nginx `listen [::]:80`, vhost selection, webroot | Fix only approved vhost; verify marker body then staging |
| HTTP-01 responds 403 | Filename, filesystem mode, SELinux label/AVC, selected vhost | Do not disable SELinux globally |
| HTTPS valid on IPv4 but expired on IPv6 | `listen [::]:443`, default vhosts, actually served SAN/expiry | Scoped listener repair; verify without `curl -k` |
| Certificate renewed but consumer still old | Exact lineage, active cert/key path, deploy hook exit code, service reload | Validate active consumer before declaring success |
| Wildcard DNS-01 failure | selfHOST auth/cleanup, scope, DNS propagation, Certbot log | Do not expose credentials or fall back to unrelated HTTP-01 |
| Global run fails for an externally hosted name | A/AAAA ownership, webroot/HTTP path, current consumers | No DNS rewrites or cert changes on wrong MX; individually quarantine only if approved |
| Backend TLS differs from MX certificate | Controller sync timer/logs, certificate fingerprints and LXC served ports | Repair sync/consumer separately; do not change MX Certbot globally |
| Ansible preflight fails | Site vars/Vault, file ownership, exact content, recent drift | No apply until the mismatch is reviewed |

## 11. Routine operating checklist and outstanding evidence

**After each real renewal:** confirm the successful ACME event; selected
deploy-hook exit status; certificate `notAfter`; the certificate served by
each intended consumer on both IP families; MTA-STS policy unchanged; backend
sync timer and IMAPS/submission presentation where relevant. Keep only
redacted operational evidence in version control.

**Weekly:** check Certbot timer and last result, upcoming expiry windows,
DNS ownership/drift, controller certificate-sync status and Nginx/Postfix
errors. Track failed unattended renewals with alerting; a successful
no-op timer scan is not enough.

**Outstanding independent validation:** the next naturally scheduled,
**actual** issuance/renewal and deploy-hook execution; continuing backend
sync after rotation; systematic alert thresholds; restore exercises. These
were not established by the successful 2026-10-11 global no-op run. Also,
the scoped Ansible playbooks **do not yet** provision all Certbot lineages,
DNS-01 hooks or gateway vhosts on a blank replacement host.

**Change policy:** prefer read-only diagnostics; backup; narrow explicit
approval; one-lineage staging; one-service change; evidence; rollback if
needed. Avoid global `certbot renew` as a routine manual test and avoid
unrelated host/domain changes.

## 12. Related project documentation

- [Mail backend architecture and cutover](MAIL.md)
- [Platform architecture](ARCHITECTURE.md)
- [Changelog](CHANGELOG.md)
- [Engineering conventions](../ENGINEERING.md)
- [Project roadmap](ROADMAP.md)
