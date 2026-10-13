# Paperless Synology SSO OIDC — staged integration

Status: **PREPARED, NOT DEPLOYED**. Supersedes the previous authentik-only
design in `docs/PAPERLESS-LDAP-SSO.md`. No authentik LXC is needed.

## Grounded current state

- Synology SSO Server is installed on the SDS and `Bergen Paperless` was
  registered as an OIDC application with the Paperless `synology` callback.
- OIDC client ID and client secret already reside inside the existing
  `ansible/vars/paperless.vault.yml` on `bp-controller` (ignored by Git).
  They must not be pasted into chat, screenshots, shell histories or Git.
- Paperless-ngx currently runs in LXC 126 with a loopback-only port and
  its existing admin account; group and family accounts have not been created.
- The sole synthetic OCR test document belongs to admin and has no additional
  user/group object ACLs. The NAS importer remains disabled.
- A working HTTPS reverse proxy route for `paperless.thebergens.net`
  is **not yet verified**. Do not perform the OIDC browser login before that.
- LDAP source groups use nesting: `Familie` has nested `Eltern` and
  `Kinder` DNs. Do not assume Synology's OIDC `groups` claim includes
  effective/transitive membership.

## Opt-in configuration staged in Ansible only

New role defaults:
- `paperless_synology_oidc_enabled: false`
- `paperless_synology_oidc_configuration_approved: false`
- `paperless_synology_oidc_discovery_url: ''`

Even with valid Vault credentials, this branch does **not** automatically
enable or redeploy OIDC. An explicit, separately reviewed deployment is
required. The existing Paperless configuration differed from the role template
for another setting; do not overwrite the active environment by blindly
applying the complete deployment role.

If an independently approved deployment enables OIDC, the template stages:
- provider app `allauth.socialaccount.providers.openid_connect`
- `provider_id=synology` to match the registered callback
- client credentials sourced only from existing encrypted Vault keys
- confirmed SSO well-known URL as the provider `server_url`
- `PAPERLESS_SOCIAL_AUTO_SIGNUP=false`
- `PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS=false`
- `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS=false`
- `PAPERLESS_DISABLE_REGULAR_LOGIN=false`
- `PAPERLESS_REDIRECT_LOGIN_TO_SSO=false`

The local Paperless `admin` remains the break-glass account.
Group sync, administrative claims, identity auto-creation and document
ingestion are not part of this stage.

## Verified Synology OIDC discovery (2026-10-13)

From an SSH session on the NAS, the following test returned a fully parsed
OIDC metadata JSON document with validated HTTPS **without** `-k`:

```bash
curl --noproxy '*' --fail --silent --show-error \\
  --resolve 'sehnde.tbergen.de:5001:127.0.0.1' \\
  'https://sehnde.tbergen.de:5001/webman/sso/.well-known/openid-configuration'
```

Confirmed:
- Exact discovery URL:
  `https://sehnde.tbergen.de:5001/webman/sso/.well-known/openid-configuration`
- Issuer: `https://sehnde.tbergen.de:5001/webman/sso`
- Authorization: `https://sehnde.tbergen.de:5001/webman/sso/SSOOauth.cgi`
- Token: `https://sehnde.tbergen.de:5001/webman/sso/SSOAccessToken.cgi`
- JWKS: `https://sehnde.tbergen.de:5001/webman/sso/openid-jwks.json`
- Userinfo: `https://sehnde.tbergen.de:5001/webman/sso/SSOUserInfo.cgi`
- RS256, authorization code, PKCE S256, groups scope/claim supported.
- Claim support does **not** establish correct nested LDAP group expansion.

**Network caveat:** The controller previously resolved
`ldap.thebergens.net -> 192.168.6.11`; TCP 636 succeeded but TCP 5001
timed out. Local verified HTTPS on the NAS does not prove that either
`bp-controller` or the Paperless LXC can reach SSO on 5001.

Run offline tests in the review worktree:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_synology_oidc*.py' -v
```

Run the strict no-credentials probe from a host only **after** it has a
reviewed network route to the Synology SSO port:

```bash
python3 ansible/scripts/paperless_synology_oidc_preflight.py \\
 'https://sehnde.tbergen.de:5001/webman/sso/.well-known/openid-configuration'
```

The preflight validates HTTPS, certificate, issuer and observed OIDC endpoints
without login or modification. It does not substitute for login testing.

## Subsequent gates

1. Verify Paperless-runtime reachability of the confirmed Well-known URL and signed issuer/JWKS/token flow; refuse
   missing or inconsistent issuer, audience, redirect, nonce, state or TLS.
   Synology SSO versions may differ; do not assume a fixed issuer path.
2. Verify restricted, TLS-protected `paperless.thebergens.net` proxy route
   to LXC 126 without exposing the backend on LAN/WAN.
3. Inspect the running Paperless 3.3.0 configuration and image; check
   generated `paperless.env` via safe structural tests **without** exposing
   secrets, and reconcile configuration drift separately.
4. Provision the four user identities under a reviewed mapping, with no
   extra superusers and no unreviewed social account linking. Check SSO
   signup/login behavior with an ordinary user.
5. Validate whether Synology provides effective `Familie` membership in
   the `groups` claim for nadja, nils and Linda. Until proven, leave
   automatic Paperless group synchronization disabled. Never infer ACLs
   from group names alone.
6. Test two normal users and a nonmember for object-level read/write denial,
   session expiration and logout, then plan the independent NAS importer.

## Official references

- https://kb.synology.com/en-us/DSM/help/SSOServer/sso_server_application_list?version=7
- https://docs.paperless-ngx.com/advanced_usage/
- https://docs.paperless-ngx.com/configuration/

No part of this document authorizes modifying the running Paperless services.
