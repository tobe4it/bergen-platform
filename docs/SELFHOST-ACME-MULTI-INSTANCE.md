# Independent reusable selfHOST wildcard certificate instances

The existing single-zone DNS-01 deployment remains supported and unchanged.
Use **one instance per DNS zone** only when more than one zone is needed.
Each instance has an independently configured DNS-API access and exactly two
zone-specific DNS TXT records, private challenge state, staging workspace and
Certbot lineage. The same reviewed Python hook supports all instances.
**Use the actual credential assigned to each ACME-API access.** Accesses may
have distinct keys even if they belong to the same selfHOST account. Reusing
the legacy key is permitted only if the provider confirms it is valid for
the new access; never infer key identity from the account alone.

This does **not** create a multi-zone SAN certificate. Each instance issues
exactly `zone` and `*.zone`. Wildcards do not cover the apex unless the apex
is also explicitly requested, and do not cover multiple DNS levels.

Additional wildcard certificates intended for web/application TLS are
**ECDSA-only**, explicitly issued by Certbot with `--key-type ecdsa` and
`--elliptic-curve secp256r1` (P-256). The playbook checks the issued
certificate's public-key algorithm in both staging and production. RSA
certificates are maintained separately where legacy SMTP interoperability
requires them; this playbook never issues an RSA companion certificate.

The optional `selfhost_acme_tls_rsa2048_compat` setting is unrelated to the
new certificate's key algorithm. It only relaxes the OpenSSL security level
for the outbound HTTPS connection to the selfHOST DNS API if that provider's
RSA-2048 TLS certificate is incompatible with the host's FUTURE crypto policy.
It does not create an RSA certificate or weaken unrelated services.

## Separation from existing installations

Legacy single-zone deployments still use:

- `/etc/letsencrypt/selfhost-acme.json`
- `/var/lib/selfhost-acme/active.json`
- the existing production Certbot lineage and its renewal profile.

Additional instances with a safe slug such as `secondary-zone` use:

- `/etc/letsencrypt/selfhost-acme.d/secondary-zone.json` (root 0600)
- `/var/lib/selfhost-acme/instances/secondary-zone/active.json` (root 0700 directory)
- `/var/lib/acme-staging/instances/secondary-zone/`
- production lineage `selfhost-dns-secondary-zone`
- staging lineage `selfhost-dns-secondary-zone-staging`

The common hook is backwards-compatible: without a `state_dir` it keeps the
original state location. A per-instance config must specify the validated
private instance state location. Existing installed hook code may be updated;
existing configuration, state and certificate lineages are not migrated.

**Public repository policy:** No real DNS names, record IDs, hostnames,
certificate lineages tied to production, API keys or contact addresses
belong in tracked files, GitHub issues or commits.

## Controller configuration (repeat for each additional zone)

First choose a unique, local instance slug. Example uses `secondary-zone`;
the examples themselves contain no production identities.

```bash
cd ~/bergen-platform
cp ansible/vars/selfhost-acme-instance.local.yml.example \
   ansible/vars/selfhost-acme-secondary-zone.local.yml
chmod 600 ansible/vars/selfhost-acme-secondary-zone.local.yml
vim ansible/vars/selfhost-acme-secondary-zone.local.yml

# Keep distinct access credentials in distinct encrypted Vault files.
umask 077
EDITOR=vim ansible-vault create \
  ansible/vars/selfhost-acme-secondary-zone.vault.yml
```

Put only the new access's complete `selfhost_acme_api_key` into
`selfhost-acme-secondary-zone.vault.yml`. Keep the original legacy access's
credential in the existing ignored `selfhost-acme.vault.yml`. If both accesses
are explicitly confirmed to share a key, they can instead reference the same
Vault, but this must be a deliberate, verified choice. Never overwrite the
legacy Vault with a new instance's key or invent a replacement key locally.
Never put a raw key in an unencrypted local variables file.

Provision exactly two dedicated `_acme-challenge` TXT slots for the new zone,
under its own ACME-API access, and enter their numeric IDs in the ignored local
YAML. Provide all relevant authoritative nameservers. Provider-side permissions
must be confirmed by an isolated staging request. If a key is shared, its
compromise can affect all accesses permitted by that key.

The existing ignored `ansible/vars/mail-tls.local.yml` supplies only the
approved source host and SSH identity. A second zone does not need a second
host, but the same playbook works with a different approved source as well.

## Offline preflight and install only

```bash
python3 -m pytest -q \
  tests/test_selfhost_acme_hook.py \
  tests/test_selfhost_acme_multi_instance.py

ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/selfhost-acme-instance.yml \
  -e @ansible/vars/mail-tls.local.yml \
  -e @ansible/vars/selfhost-acme-secondary-zone.local.yml \
  -e @ansible/vars/selfhost-acme-secondary-zone.vault.yml \
  --vault-id infra@prompt --syntax-check

ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/selfhost-acme-instance.yml \
  -e @ansible/vars/mail-tls.local.yml \
  -e @ansible/vars/selfhost-acme-secondary-zone.local.yml \
  -e @ansible/vars/selfhost-acme-secondary-zone.vault.yml \
  --vault-id infra@prompt
```

Without explicit issuance flags this deploys only the shared hook and that
instance's private configuration and verifies both authoritative TXT slots
are in their expected idle state. It makes no DNS API request and does not
issue a certificate, reload Nginx or change a live lineage. If the
installation fails, investigate before running a staging challenge.

## Explicit isolated staging (DNS API writes)

After the no-issue run has passed, use the SAME command with:

```bash
-e selfhost_acme_run_staging=true
```

This creates a separate **untrusted** Let's Encrypt staging certificate
under that instance's staging workspace. It must never be installed into
production. The hook waits for authoritative DNS propagation; both TXT slots
must return to idle. An uncertain API result reserves the slot and blocks
further issuance pending investigation. Do not delete the private state
file to bypass this safety interlock.

## Explicit new production lineage

After staging succeeds and both slots are idle, use the SAME playbook with:

```bash
-e selfhost_acme_issue_production=true
```

**Do not combine staging and production flags.** This operation is opt-in
and requires the isolated staging certificate with the correct apex and
wildcard SANs. It refuses to replace an existing renewal profile at
`/etc/letsencrypt/renewal/selfhost-dns-<instance>.conf`.

The resulting certificate is created under
`/etc/letsencrypt/live/selfhost-dns-<instance>/`. Certbot stores the
instance-specific DNS-01 auth/cleanup hook commands in that lineage's
renewal profile. Confirm the profile, expiry and matching key pair before
routing any service to the new certificate.

Renewal still requires a working Certbot timer, functional DNS API and
correct permissions. **Issuance does not change any Nginx VHost or install
a deploy hook.** Consumers must be switched in a separate scoped operation,
with `nginx -t`, certificate and SAN checks, and rollback. Automatic service
reloads after future renewals must be verified separately.

## Recover an isolated instance after an unsuccessful DNS API request

If staging fails before DNS publication (for example, the API responds with
HTTP 401), the hook deliberately retains the affected instance's local
`reserved` entries. Do not remove the state file, attempt Certbot again,
or run the **legacy** recovery helper without `--instance`.

The shared recovery script accepts a strictly validated instance slug and
derives the root-owned JSON config and state directory independently:

```bash
sudo python3 /usr/local/libexec/selfhost_acme_recover.py \
  --check --instance secondary-zone
```

The read-only readiness check requires no running Certbot process, one or two
well-formed reservations solely for this instance's configured record IDs,
every configured authoritative DNS server to show **both** idle markers and
none of the recorded challenge tokens. It also checks the configured
`state_dir` exactly matches the private path derived from the slug.

Only after the check reports `READY` and an operator authorizes recovery may
the command be repeated with `--apply --instance secondary-zone`. This
creates a root-only protected backup in the instance's own state directory
before clearing its reservations. No selfHOST API requests, DNS changes,
certificate changes or service reloads are performed. Recheck for
`ALREADY_CLEAN` afterwards.

From Ansible, select the instance explicitly with
`-e selfhost_acme_reconcile_instance=secondary-zone` alongside the
matching ignored instance local YAML. Without this extra variable the
recovery playbook continues to operate on the **legacy** instance only.

After a 401 response, verify that the dedicated provider access authorizes
the two TXT record IDs and update only the matching instance's encrypted
Vault, then run installation-only before attempting staging again.

## Operational safety

- Do not restart Postfix, Collabora or Nginx as part of issuance.
- Do not change system-wide crypto policies for a DNS API compatibility issue;
  the existing optional per-endpoint TLS verification mode remains available.
- A successful dry run of Certbot without a due certificate does not prove
  the next unattended renewal.
- If an instance's `active.json` is nonempty, inspect and recover only
  **that instance's** reservations. Do not apply the legacy recovery playbook
  to a second instance without extending its path scoping first.
- Re-running a completed **production** issuance with the apply flag is
  intentionally refused if its lineage already exists. Run normal scoped
  renewal procedures instead.

See [selfHOST DNS-01 implementation](SELFHOST-ACME-DNS01.md) and
[Mail TLS operations](MAIL-TLS-OPERATIONS.md).
