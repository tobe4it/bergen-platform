# selfHOST ACME DNS-01 API: Certbot hooks

This implementation uses selfHOST's current ACME-DNS API, not its historical
DynDNS endpoint. The existing production Certbot lineage is not changed by
checking out these files.


## Preferred: manage the entire setup from the Ansible controller

No interactive SSH session on the certificate source is necessary. The
playbook deploys the reviewed Python hook to the source and creates the
root-owned 0600 API configuration there. It leaves production Certbot
unchanged. Every real DNS name, record ID, source username, account email,
and credential remains in Git-ignored local files.

On the controller:

    cd ~/bergen-platform
    cp ansible/vars/selfhost-acme.local.yml.example \
       ansible/vars/selfhost-acme.local.yml
    chmod 600 ansible/vars/selfhost-acme.local.yml
    vim ansible/vars/selfhost-acme.local.yml

Provide zone, exactly two numeric record IDs, both authoritative
nameservers and an ACME contact email in that local YAML. Use the EXISTING
ignored ansible/vars/mail-tls.local.yml for the source SSH identity and the
current Certbot certificate path; do not duplicate this infrastructure data.

Create the only secret separately, encrypted by Ansible Vault:

    umask 077
    EDITOR=vim ansible-vault create ansible/vars/selfhost-acme.vault.yml

Vault plaintext contents while editing (never commit or paste the key):

    selfhost_acme_api_key: "CHANGE_ME_COMPLETE_ID.DOT_SECRET"

The encrypted Vault file is also Git-ignored. Restrict it to mode 0600.
Ansible needs the Vault password at every execution, and the secret is
transferred using normal verified SSH plus privilege escalation. Vault
protects the secret at rest on the controller, not in target process memory.

Run offline guardrails first:

    python3 -m pytest -q \
      tests/test_selfhost_acme_hook.py tests/test_selfhost_acme_bootstrap.py
    ansible-playbook \
      -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/selfhost-acme-bootstrap.yml \
      -e @ansible/vars/mail-tls.local.yml \
      -e @ansible/vars/selfhost-acme.local.yml \
      -e @ansible/vars/selfhost-acme.vault.yml \
      --syntax-check --ask-vault-pass

Then perform the **install-only** Ansible run:

    ansible-playbook \
      -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/selfhost-acme-bootstrap.yml \
      -e @ansible/vars/mail-tls.local.yml \
      -e @ansible/vars/selfhost-acme.local.yml \
      -e @ansible/vars/selfhost-acme.vault.yml \
      --ask-vault-pass

Expected: HOOK_INSTALLED and TWO_IDLE_SLOTS_VERIFIED. This performs no
ACME issuance and no API write requests. A second execution should be
idempotent.

Once install-only has passed and API slot state is known, explicitly run
an isolated staging issuance from the SAME controller:

    ansible-playbook \
      -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/selfhost-acme-bootstrap.yml \
      -e @ansible/vars/mail-tls.local.yml \
      -e @ansible/vars/selfhost-acme.local.yml \
      -e @ansible/vars/selfhost-acme.vault.yml \
      -e selfhost_acme_run_staging=true \
      --ask-vault-pass

The staging pass calls the external selfHOST API and the Let's Encrypt
staging CA, changing temporary TXT values. It cannot update the productive
Certbot lineage, because it uses a different --config-dir and --cert-name.
Do NOT run staging until the install-only status is successful, and never
deploy its untrusted staging certificate to a live service.

Production Certbot migration is intentionally a separate, reviewable step
after successful staging and a version-specific check of certbot reconfigure.
Avoid editing its renewal INI manually or testing against production first.

## Preconditions

- selfHOST hosts the authoritative zone.
- Create one ACME API access with TWO TXT slots for the same relative name:
  _acme-challenge.
- Keep the assigned two record IDs and complete API key on the certificate
  source in a root-only local file. NEVER commit real domains, record IDs,
  hostnames, passwords or API keys to this repository.
- The certificate source needs Python 3, dig (bind-utils), and certbot.

## Site-local root-only configuration

Create /etc/letsencrypt/selfhost-acme.json on the source with this shape:

    {
      "api_key": "CHANGE_ME_ID.SECRET",
      "zone": "example.invalid",
      "record_ids": [1111111, 2222222],
      "nameservers": ["ns1.example.invalid", "ns2.example.invalid"]
    }

The zone must match the apex and wildcard Certbot identifiers. Both record
IDs must belong to slots named _acme-challenge within that zone.

On the certificate source:

    sudo install -o root -g root -m 0600 /dev/null /etc/letsencrypt/selfhost-acme.json
    sudo vim /etc/letsencrypt/selfhost-acme.json
    sudo chmod 0600 /etc/letsencrypt/selfhost-acme.json
    sudo chown root:root /etc/letsencrypt/selfhost-acme.json

Do not print the credential file, log the HTTP request body, run shell tracing,
or place the API key on the command line.

The generic Python hook is scripts/selfhost_acme_hook.py. Transfer ONLY this
public source code from the controller, never the key material:

    scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
      scripts/selfhost_acme_hook.py USER@SOURCE:~/selfhost_acme_hook.py

On the source:

    sudo install -d -o root -g root -m 0755 /usr/local/libexec
    sudo install -o root -g root -m 0755 \
      ~/selfhost_acme_hook.py /usr/local/libexec/selfhost_acme_hook.py
    rm ~/selfhost_acme_hook.py
    command -v dig && command -v python3 && command -v certbot

The hook stores protected state under /var/lib/selfhost-acme. A lock serializes
access to the two records; an uncertain API outcome retains a reservation and
requires manual inspection. Do not erase state while Certbot may be running.

## Behavior

Each present action sends JSON containing api_key, action, record_id and
content. HTTP 202 only means accepted: the hook also polls EVERY configured
authoritative nameserver for the exact TXT value before returning success.
The auth hook writes only the numeric record ID to stdout for
CERTBOT_AUTH_OUTPUT. Cleanup uses that exact ID and validation value, waits
for the corresponding selfhost-api-idle-RECORD_ID, and only then frees it.

## Test sequence

1. On the controller run offline tests without API requests:

       python3 -m pytest -q tests/test_selfhost_acme_hook.py
       python3 -m py_compile scripts/selfhost_acme_hook.py

2. On the certificate source confirm the two TXT slots are idle on both
   authoritative nameservers using the real site-specific values:

       dig +short TXT _acme-challenge.example.invalid @ns1.example.invalid
       dig +short TXT _acme-challenge.example.invalid @ns2.example.invalid

3. Keep the productive renewal configuration unchanged. A separate
   Let's Encrypt staging issuance uses independent directories and a
   distinct certificate name. This WILL briefly update the API TXT slots,
   but CANNOT overwrite the existing productive Certbot lineage.

       sudo certbot certonly \
         --staging --non-interactive --agree-tos \
         --email YOU@example.invalid \
         --config-dir /var/lib/acme-staging/config \
         --work-dir /var/lib/acme-staging/work \
         --logs-dir /var/lib/acme-staging/log \
         --cert-name selfhost-dns-api-staging \
         --manual --preferred-challenges dns \
         --manual-auth-hook '/usr/bin/python3 /usr/local/libexec/selfhost_acme_hook.py auth' \
         --manual-cleanup-hook '/usr/bin/python3 /usr/local/libexec/selfhost_acme_hook.py cleanup' \
         -d example.invalid -d '*.example.invalid'

   Replace the placeholder domains and email locally. Do not use --expand,
   --force-renewal, or the existing productive cert name in this staging test.
   The resulting staging certificate must NEVER be installed in mail services.

4. After successful staging issuance inspect the authoritative DNS values.
   Both slots should have their separate selfHOST idle values again.

Only after successful staging validation and review should the productive
Certbot renewal configuration be adapted to these hooks. The existing mail
distribution timer already operates independently of certificate issuance.

## Limitations

The hook intentionally fails closed on unauthorized domain names, occupied
slots, uncertain API outcomes, or missing DNS propagation. It does not
automatically clear stale reservations, install a Certbot timer, modify
existing renewal files, or activate renewed certificates on the source.
Monitoring and recovery remain separate operational tasks.


## RHEL FUTURE and selfHOST RSA-2048 HTTPS compatibility (opt-in)

A machine under RHEL crypto-policy FUTURE can reject a valid provider TLS
certificate with a 2048-bit RSA leaf (OpenSSL verify error 66). FUTURE
requires >=3072-bit RSA. Do NOT change the machine-wide crypto policy or
disable HTTPS verification. Requesting a stronger certificate from the
provider remains the preferred permanent correction.

A strictly scoped compatibility option is available ONLY for the fixed
HTTPS endpoint in scripts/selfhost_acme_hook.py. The setting defaults to
false. To enable it for the selfHOST ACME hook ONLY, add the following to
the Git-ignored controller file ansible/vars/selfhost-acme.local.yml:

    selfhost_acme_tls_rsa2048_compat: true

The bootstrap playbook transfers this flag into the root-only source
configuration as tls_rsa2048_compat. It changes no other system services.
When enabled, the hook creates a separate Python TLS context with:

- CA chain verification still REQUIRED;
- hostname verification still ENABLED;
- TLS version >=1.2;
- TLS 1.2 cipher suites restricted to ephemeral ECDHE and AES-GCM;
- OpenSSL security level 2, permitting RSA-2048 instead of FUTURE RSA-3072.

TLS 1.3 suites follow OpenSSL's TLS 1.3 configuration. This workaround is
not the same as turning verification off. It does, however, make an explicit
cryptographic exception for the provider endpoint. It must not be adopted
globally or applied to unrelated HTTPS operations.

First use ansible/playbooks/selfhost-acme-staging-diagnostics.yml and inspect
the read-only task "Show verified RSA2048 compatibility probe classification".
A returned HTTP status, including 4xx/405, means the TLS connection and
server identity verification succeeded. The GET request does NOT carry a
credential and does NOT modify DNS.

After that read-only TLS test succeeds and the local reserved/remote idle
state has been safely reconciled, rerun bootstrap installation-only (without
selfhost_acme_run_staging=true) to deploy the opt-in configuration. Do not
repeat the staging issuance while any local TXT slot remains reserved.


## Recover abandoned TXT reservations after a failed staging hook

If a previous Certbot staging invocation failed while establishing HTTPS, the
hook may have kept both source-side slots marked "reserved" despite BOTH
authoritative DNS servers showing their idle values. Do NOT blindly remove
/var/lib/selfhost-acme/active.json or repeat Certbot while these reservations
are present. Use the controller-only reconciliation playbook:

1. Confirm the provider endpoint's read-only compatibility probe returns
   certificate_verification=enabled, hostname_verification=enabled, and a
   regular HTTP status (often 405 for GET).
2. Add to the ignored ansible/vars/selfhost-acme.local.yml:

       selfhost_acme_tls_rsa2048_compat: true

   This keeps the host-wide crypto-policy FUTURE unchanged and only opts the
   fixed provider HTTPS hook into RSA-2048 compatibility, with full CA/hostname
   verification. It is an explicit exception, not a global default.
3. On the controller test the recovery logic offline:

       python3 -m pytest -q \
         tests/test_selfhost_acme_hook.py \
         tests/test_selfhost_acme_bootstrap.py \
         tests/test_selfhost_acme_recover.py

4. Re-run ansible/playbooks/selfhost-acme-bootstrap.yml WITHOUT setting
   selfhost_acme_run_staging=true. This updates only the installed hook/local
   config and verifies both DNS idle values, with no CA issuance.
5. From the controller run the safe recovery preflight (requires only the
   two ignored non-secret YAML files):

       ansible-playbook -i ansible/inventory.yml \
         -i ansible/inventory.local.yml \
         ansible/playbooks/selfhost-acme-reconcile.yml \
         -e @ansible/vars/mail-tls.local.yml \
         -e @ansible/vars/selfhost-acme.local.yml \
         --vault-id infra@prompt

   Expected READY: exactly two abandoned reserved slots and both DNS slots
   idle; both checks occur with the same protected state lock.
6. Only if READY was observed, explicitly apply the local-only reconciliation:

       ansible-playbook -i ansible/inventory.yml \
         -i ansible/inventory.local.yml \
         ansible/playbooks/selfhost-acme-reconcile.yml \
         -e @ansible/vars/mail-tls.local.yml \
         -e @ansible/vars/selfhost-acme.local.yml \
         -e selfhost_acme_reconcile_apply=true \
         --vault-id infra@prompt

   This refuses to run if a Certbot process is present, requires the two
   known reserved tokens and corresponding authoritative DNS idle values,
   creates a private root-only JSON backup, and resets ONLY local hook state.
   It NEVER calls the selfHOST API, deletes TXT records or changes any cert.
   Repeat runs are idempotent (ALREADY_CLEAN).

After that, rerun the read-only diagnostic and verify both slots are idle
and no reservations remain before attempting any new staging certificate.
If a guard fails, do not force the recovery or clear state manually. Review
the failed condition first.


## Review and activate existing production Certbot renewal settings

Once a separate Let's Encrypt staging issuance has succeeded, both slots are
back at their idle values, and the read-only production preflight has passed,
prepare the EXISTING production Certbot lineage to use the hook. The
preferred approach is Certbot 2.3+ "reconfigure": it first performs a
staging-backed test, then persists the new renewal settings if successful.
It does not replace the live certificate. It does temporarily publish
ACME TXT challenges. Do not edit Certbot renewal INI by hand.

From the controller, first run the offline guardrail tests:

    python3 -m pytest -q tests/test_selfhost_acme_production_reconfigure.py
    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/selfhost-acme-production-reconfigure.yml \
      -e @ansible/vars/mail-tls.local.yml \
      -e @ansible/vars/selfhost-acme.local.yml \
      --vault-id infra@prompt --syntax-check

Next run WITHOUT the apply flag. This verifies the live fullchain/private key,
expected single-lineage config, stopped Certbot activity, idle authoritative
TXT slots and existing backup status; it performs no API write and never
reconfigures Certbot:

    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
      ansible/playbooks/selfhost-acme-production-reconfigure.yml \
      -e @ansible/vars/mail-tls.local.yml \
      -e @ansible/vars/selfhost-acme.local.yml \
      --vault-id infra@prompt

Expected: current_renewal_configuration=renewal_config_status=READY, with
configuration=READY_FOR_EXPLICIT_APPLY. If any guard fails, stop.

Only after an operator reviews that result, authorize the configuration
change using the exact same command plus:

    -e selfhost_acme_reconfigure_apply=true

The guarded apply first makes a root-only backup of the existing renewal
profile under /var/lib/selfhost-acme/ and runs Certbot reconfigure against
the EXACT existing --cert-name, using the installed manual auth/cleanup hooks.
The staging validation temporarily changes TXT values, but it must leave
the productive fullchain and private key hashes unchanged. Post-checks
require saved hook paths to be exact and all TXT slots to return idle.

Certbot's existing renew timer may then renew the lineage automatically
when it becomes due. However, Certbot timer enablement does not prove that
other lineages on the same host are healthy; separately review invalid
renewal profiles and test relevant renewals without applying broad changes.

If a reconfigure attempt fails, do not immediately retry: use the existing
read-only diagnostic and recovery workflows to inspect reserved TXT slots.
The root-only backup stays available. Do not restore it blindly because
the failed run may have modified the profile before reporting a failure.


## Operating the existing Certbot renewal timer after production reconfigure

After the existing production lineage has passed guarded reconfigure, perform
an initial read-only audit from the controller. This checks whether
certbot-renew.timer is enabled and active, its most recent and next expected
trigger, the last certbot-renew.service result, deploy-hook presence and direct
TLS certificate references for selected source services. It does **not**
request a certificate, run certbot renew, modify DNS, or reload daemons.

    cd ~/bergen-platform
    python3 -m pytest -q tests/test_mail_source_renewal_runtime_readonly.py
    ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \\
      ansible/playbooks/mail-source-renewal-runtime-readonly.yml \\
      -e @ansible/vars/mail-tls.local.yml \\
      --vault-id infra@prompt

Inspect timer_activestate, timer_unitfilestate, timer_nextelapseusecrealtime,
service_result and service_execmainstatus, then the source service
certificate-reference classifications. A false direct reference does NOT
prove the service does not use the certificate: aliases, SNI, TLS maps,
symlinked copies, alternative config syntax and downstream proxying require
further inspection. Check any existing hooks' **contents** separately before
adding a deploy hook, because multiple hooks can overlap. A timer being
active does not itself prove that an unattended renewal succeeds.
