# Open WebUI OIDC

This additive configuration targets the existing rootful Podman Quadlet deployment
of Open WebUI v0.10.2. It adds a protected environment file via a Quadlet drop-in;
it does not replace the container image, volumes, LDAP configuration, or proxy.
Repository documentation is English; bilingual operator guides belong in the Wiki.

## Prerequisites

- Existing `/etc/containers/systemd/open-webui.container` and `open-webui.service`.
- A current restorable backup of application data and a tested local administrator login.
- An independent OIDC client with redirect `https://<webui-host>/oauth/oidc/callback`.
- HTTPS discovery, token, userinfo and JWKS endpoints reachable from the container.
- A working browser path to both the application and identity provider.

Create `ansible/vars/ai-oidc.local.yml` from the example. Store
`vault_open_webui_oidc_client_secret` in `ansible/vars/ai-oidc.vault.yml` using
`ansible-vault create --vault-id ai@prompt`. Both local files are ignored by Git.
Never send the secret in command-line extra variables or paste it into diagnostics.

Run `configure-open-webui-oidc.yml` with the existing inventories, the local settings
and Vault as extra variable files. Explicitly set
`open_webui_oidc_deployment_approved`, `open_webui_oidc_backup_confirmed` and
`open_webui_oidc_local_admin_confirmed` to true only after completing the checks.
The playbook restarts Open WebUI when its configuration changes. Syntax checks do
not validate the live service or complete an SSO login.

## Initial access policy

Synology advertises `openid email groups`, not `profile`. The display-name claim
is `username`. PKCE S256 and client_secret_basic are supported by its discovery.
Keep the local login form and existing LDAP settings. New OIDC users receive the
pending role; an administrator must approve access. Automatic group and role
mapping are disabled by default. Group synchronization can be enabled as described below;
automatic role mapping remains disabled.
Email-based merging is disabled. An existing LDAP/local account with the same email
will not automatically link: verify directory email ownership, back up data, and
plan account linking before testing with an existing account. Do not delete accounts
or create replacement accounts to work around this; chats remain owned by user IDs.

## Network validation on 2026-10-15

The deployed application is reachable via `https://ai.thebergens.net`.
Synology discovery at
`https://sehnde.tbergen.de:5001/webman/sso/.well-known/openid-configuration`
returned HTTP 200 with certificate validation on 192.168.6.11. The other DNS answer,
192.168.2.145, timed out from bergen-ai. Discovery also succeeded inside Open WebUI,
but mixed reachable/unreachable answers can cause delay or intermittent failures.
Resolve this through scoped DNS/network configuration; retain the HTTPS hostname
and issuer rather than replacing them with an IP. No DNS or firewall changes are
performed by this playbook.

## Acceptance and rollback

After activation, verify local administrator login, the SSO button, callback,
pending-user approval, a model request and preservation of existing chats.
Live validation on 2026-10-15 confirmed a checked offline data backup, local
administrator access, successful deployment and HTTP 200 from the application.
After correcting the client secret in Vault, browser SSO completed and created a
separate account with the pending role. The existing administrator remained present.
Pending-user approval, a model request and preservation of existing chats have
not yet been reported as verified.

The operator is rotating the diagnostic-exposed client secret separately from the
code release. Update the Synology OIDC application secret, edit
`ansible/vars/ai-oidc.vault.yml` with `ansible-vault edit --vault-id ai@prompt`,
then rerun the deployment playbook with the existing local settings and approval
flags. A configuration change restarts Open WebUI. Complete a fresh browser SSO
login after rotation; an existing session does not verify the new secret.
Never commit secrets or diagnostic output containing them.

To disable this integration, remove only
`/etc/containers/systemd/open-webui.container.d/90-oidc.conf`, run
`systemctl daemon-reload`, then `systemctl restart open-webui.service`.
The protected environment file may be removed after rollback. Do not remove the
base Quadlet, application volume, LDAP environment, or database. This rollback
removes the provider configuration; it does not undo accounts created during SSO tests.

Reference: https://github.com/open-webui/open-webui/blob/v0.10.2/backend/open_webui/config.py

## LDAP group synchronization (Open WebUI v0.10.2)

The reviewed group names are `Familie@bergen.intern`, `Eltern@bergen.intern` and
`Kinder@bergen.intern`. Synology must emit these exact names in the `groups` claim.
There is no translation or inferred parent/child membership.

Set `open_webui_oidc_group_management: true` and copy `open_webui_oidc_groups`
from the local example. Store a valid local administrator bearer token as
`vault_open_webui_admin_token` in the ai Vault; do not paste it into shell commands
or diagnostics. Run the existing OIDC playbook with the same approval flags.
The token is used only for loopback API calls and is not written to the OIDC
container environment. API identity, list and create tasks suppress their output.
An API key is usable only if the installation permits these admin endpoints;
a valid administrator session bearer token can also authenticate them.

Before activating synchronization, the playbook verifies the administrator token,
rejects duplicate target names and creates only missing groups. Existing groups,
permissions and members are not overwritten by provisioning. New groups have no
additional feature grants (a nonempty permissions object avoids copying global defaults
into the group during login), and group sharing is disabled initially. Global default
permissions still apply. Review model/knowledge access separately before granting it.
Re-running provisioning requires the administrator token again. Check mode skips
API provisioning and cannot establish that groups or credentials are ready.

`ENABLE_OAUTH_GROUP_CREATION=false` prevents arbitrary groups from being created
from claims. The native synchronizer can nevertheless match ANY existing Open WebUI
group by name; the provisioning list is not a login-time allowlist.
Membership is updated on a fresh OIDC login, not continuously. Manual membership
assignments can be removed by synchronization. Local login does not synchronize
OIDC membership. Pending remains the default role, and roles are not mapped from groups.

### Revocation limitation

In the v0.10.2 `OAuthManager.update_user_groups` implementation, membership removal
is conditional on a nonempty incoming group list. A missing or empty groups claim
therefore leaves existing memberships in place. Do not rely on this version for
complete automatic revocation. Remove access manually in Open WebUI when needed;
this configuration does not invalidate existing sessions or implement an upstream fix.
Disabling group synchronization also leaves previously assigned memberships intact.

Test fresh login with the expected family/parent or family/child memberships,
removal of one group while another remains, and the empty-claim limitation.
Verify that pending accounts remain pending and restricted models/knowledge are
inaccessible to a separate unauthorized test user. Live group acceptance is pending.

Source: https://github.com/open-webui/open-webui/blob/v0.10.2/backend/open_webui/utils/oauth.py
