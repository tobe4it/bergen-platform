# MQ LDAP preparation

The evaluated endpoint is `ldaps://ldap.thebergens.net:636`. Users remain under
`cn=users,dc=bergen,dc=intern`; groups under `cn=groups,dc=bergen,dc=intern`.
Keep site addresses and bind credentials in ignored local variables / Vault.

## Persistent CA trust

From the controller repository root:

```sh
git pull --ff-only
ansible-playbook ansible/playbooks/mq-ldap-trust.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml --ask-vault-pass
```

Targets only the existing `bergen-mq-lab` and `bergen-mq-lab-b` inventory hosts,
one at a time. Stops the play on failure. Restarts a container if its trust file,
mount, or imported CA is missing/changed. Requires an existing active service;
does not create LXCs, alter firewall policy, switch CONNAUTH or grant authorities.
The Quadlet edit is backed up. Certificate input is public and root-owned.

The role supplies `/etc/bergen-mq-lab/trust/ldap/tls.crt` through a read-only
mount at `/etc/mqm/pki/trust/ldap`; IBM imports it when the container starts.
The regular `mq_lab` role preserves this mount and deployed CA on later runs.
For new deployments, explicitly set `mq_lab_install_ldap_trust: true` in local
variables to install the CA. False/default does not revoke an installed CA.

Source: https://letsencrypt.org/certs/isrg-root-x2.pem (self-signed root),
checked byte-for-byte against the controller-side development environment's
system trust-store copy when this change was prepared.
SHA-256 certificate fingerprint:
`69:72:9B:8E:15:A8:6E:FC:17:7A:57:AF:B7:17:1D:FC:64:AD:D2:8C:2F:CA:8C:F1:50:7E:34:45:3C:CB:14:70`.
The public root certificate is bundled for reproducible, offline distribution.

Observed LDAP chain: leaf -> YE1 -> Root YE -> ISRG Root X2. The server must
continue providing its intermediate certificates. The leaf is not pinned.
This adds CA trust to the shared MQ repository, not a per-LDAP-only trust store.

Verification checks the input fingerprint, imported CA label, running MQ command
processing and preservation of QMNAME, CONNAUTH and SSLKEYR. It does not yet prove
a GSKit LDAP handshake or user authentication through MQ. Run the existing REST
readiness / audit checks after the restart as well.

## Remaining activation work

Verify LDAP user objectClass and the directory lookup identity/access policy.
Then provision IDPWLDAP with SEARCHGRP/member, uid user names and cn group names,
review the existing container authentication service and administrative access,
and activate one QMgr at a time with a recorded rollback configuration.
Grant only the required test rights to MQBERGENLAB / MQBERGENLABB; MQservice is
not an authorization grant. Require positive and cross-user denial tests.
TLS 1.3 negotiated by OpenSSL is preparation evidence, not proof of the protocol
used by MQ's LDAP client or of server-side TLS 1.2 rejection.

To revoke the added trust, remove only the managed LDAP public certificate from
the host directory and recreate the container; keep other PKI files intact.
Do not edit `/run/runmqserver/tls/key.kdb` as the persistent source of truth.
