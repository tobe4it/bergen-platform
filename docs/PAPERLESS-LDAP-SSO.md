# Paperless-ngx LDAP sign-in via authentik / OIDC (staged design)

Status: **DESIGN ONLY**. No IdP, SSO, group auto-sync, proxy route or importer is deployed by this branch. The running Paperless instance stays unchanged, including the admin break-glass login.

## Identity / authorization boundaries

```text
Synology/OpenLDAP (authoritative: users, passwords, groups)
          | LDAPS 636, authenticated read-only sync, validated server cert
          v
authentik (separate isolated runtime; no password writeback/cache)
          | OIDC authorization code, TLS, exact audience/issuer/redirect
          v
Paperless-ngx (dedicated LXC 126, through restricted HTTPS reverse proxy)
          | Paperless object permissions
          v
documents on local dedicated ZFS storage
```

Do not install authentik inside the Synology NAS, Paperless application
container, or the privileged Ansible controller. First review a separate
unprivileged LXC, storage, resource/backup allocation and a restricted
network path. Neither Paperless nor authentik should become publicly
reachable by default.

## Identity mapping (strict allowlist)

- LDAP root: `dc=bergen,dc=intern`. Existing Synology tree uses
  `cn=users` and `cn=groups`; verify live schema before writing filters.
- Human accounts: `thomas`, `nadja`, `nils`, `Linda` (preserve actual
  LDAP canonical spelling after inspection).
- Allowed Paperless authorization groups: exactly `Eltern` and `Familie`.
  The directory's `@bergen.intern` suffix is not the Paperless group name.
- Expected `Eltern`: thomas and nadja.
- Expected `Familie`: thomas, nadja, nils and Linda.
- Exclude LDAP `admin`, technical/service accounts and unknown principals
  from family auto-enrollment.
- No LDAP admin group maps to Paperless admin. The local Paperless `admin`
  remains a distinct break-glass identity. Do not enable OIDC staff or
  superuser-group sync.
- OIDC subject identifiers must remain stable. Test username casing,
  uniqueness and account linking before permitting any automatic signup.
- The technical Paperless importer, if later introduced, is noninteractive
  and must not be an eligible human OIDC identity.

## authentik LDAP source

Use `ldaps://ldap.thebergens.net:636`, verified server hostname and
trusted CA chain. The authentik LDAP source needs the TLS verification
certificate explicitly configured; an empty field skips validation, it
does **not** use the container's normal trust store.

- Read-only, least-privilege bind identity with secret only in dedicated
  encrypted Ansible Vault (never committed or printed).
- Synchronize users and groups from LDAP; verify group membership schema
  (`memberUid` + `uid`, or `member` + DN) before configuring mappings.
- `Update internal password on login = off`.
- `User password writeback = off`.
- No LDAP writes, no automatically provisioned LDAP accounts.
- Define a restrictive Paperless-app access policy and use only the exact
  authorized groups in its OIDC `groups` claim.
- Reject login if directory/TLS verification fails. Assess LDAP/account
  deactivation and authentik cache/session expiry before enabling access.

## Paperless OIDC boundary

The existing Paperless backend is loopback-only on LXC 126.
A reviewed LAN-restricted HTTPS proxy route is prerequisite: browser
redirects, the OIDC issuer/discovery URL, callback URI and server-to-server
token/JWKS lookups must all resolve consistently with trusted certificates.

Paperless supports django-allauth OpenID Connect integration via:
- `PAPERLESS_APPS` (the OIDC provider app)
- `PAPERLESS_SOCIALACCOUNT_PROVIDERS` (exact issuer discovery, client ID,
  vault-protected client secret and exact redirect URI)
- `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS` and a `groups` claim, **only after
  confirming support in the pinned running Paperless image**.
- Paperless groups `Eltern` and `Familie` must exist before group sync.
  Login-time group sync does not revoke existing sessions immediately.
- No self-service account creation for unknown directory users; stage and
  test carefully whether pre-created Paperless users or restricted OIDC
  social signup are necessary.
- Keep `PAPERLESS_DISABLE_REGULAR_LOGIN=false` until OIDC login and
  recovery have been tested. Retain a separately protected local admin
  break-glass path.
- Never enable automatic staff or superuser grants through group claims.

Group membership grants only the intended *document read* rights and
the minimum required model permissions. It does **not** create per-document
permissions. Proven trusted NAS source -> owner/group assignment remains
the separate ingestion safety gate.

## Required gates, in order

1. Read-only LDAPS TLS handshake/hostname/CA verification **from controller**,
   then repeat from the proposed authentik runtime network namespace.
   See `ansible/scripts/paperless_ldap_tls_preflight.sh`.
2. Read-only LDAP schema inspection using a reviewed bind identity: base DN,
   human accounts, group membership attribute and group names. No passwords
   or whole-directory exports in logs.
3. Choose and preflight a dedicated authentik LXC, persistent PostgreSQL
   storage, backup, system resources, reverse proxy and firewall policy.
4. Start authentik in isolation; test a single non-admin LDAP identity and
   the negative cases (nonmember, deactivated user, invalid certificate,
   unexpected claim or issuer).
5. Review **actual running Paperless version and config** before adding
   OIDC settings. Existing local environment differs from the repo template:
   do not blindly redeploy/overwrite it.
6. Provision Paperless `Eltern`/`Familie` with least privileges, verify
   actual group claim mapping with two normal users, ensure `admin` cannot
   be enrolled via LDAP, and test deprovisioning/session expiry.
7. After successful internal HTTPS/OIDC tests, review any local-login change.
   Keep the NAS importer and recursive ingestion disabled throughout.

## References

- https://docs.goauthentik.io/users-sources/sources/protocols/ldap/
- https://docs.goauthentik.io/add-secure-apps/providers/oauth2/
- https://docs.paperless-ngx.com/advanced_usage/
- https://docs.paperless-ngx.com/configuration/

No action in this document authorizes a live infrastructure change.
