# selfHOST ACME DNS-01 API: Certbot hooks

This implementation uses selfHOST's current ACME-DNS API, not its historical
DynDNS endpoint. The existing production Certbot lineage is not changed by
checking out these files.

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
