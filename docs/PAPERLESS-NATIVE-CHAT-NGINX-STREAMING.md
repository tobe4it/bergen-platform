# Paperless native AI chat: targeted Nginx streaming repair

Status: **staged in feature branch, not deployed**, 22 October 2026.
Independent of Paperless Tag sharing, document ACL and the Django child
security test. No changes to Paperless, CT126 or Ollama.

## Verified incident evidence

- Native Django authenticated child E2E passed: parent document 403, family
  direct chat response with reference, and archive-wide chat with reference.
  The browser / OIDC path is **not** established by that test.
- Nginx CT125 `bergen-proxy`, vhost
  `50-internal-paperless.thebergens.net.conf`, connects to the existing
  `http://127.0.0.1:18000` dedicated SSH local forwarding port.
- At 07:18:17, 07:21:06 and 07:28:18 UTC on 2026-10-22, requests to
  `POST /api/documents/chat/` returned HTTP 200 and zero body bytes,
  with Nginx error-log evidence
  `upstream timed out ... while reading upstream` (READ_BODY).
  A fourth request ended HTTP 499 with zero bytes.
- Existing Paperless vhost has server-level
  `proxy_read_timeout 120s`, no explicit `proxy_buffering` and
  no dedicated Chat location. A successful HTTP header is not proof of
  a complete streamed response.

Hypothesis: Nginx reads response headers but pauses waiting for the
slow first/next model-stream bytes; Nginx response buffering also
prevents immediate forwarding. The proposed change is a **targeted
experiment**, not proof that the model or Safari will work afterward.

## Exact production-scope change

The dedicated location `location = /api/documents/chat/` contains:
`proxy_pass http://127.0.0.1:18000`,
`proxy_http_version 1.1`,
`proxy_read_timeout 300s`, `proxy_buffering off`, and the **same
seven forwarded HTTP headers** as `location /`.
The route is exact-match; all other paths, HTTPS and certificate files,
allow/deny CIDRs, server-level security headers, Nginx proxy settings,
Bergen-AI vhost, SSH transport and application are unchanged.
Server-level `allow` / `deny` and security `add_header` statements
are inherited by the exact location because none are overridden there.

The restricted repair script:
1. Refuses wrong CT125 hostname, unexpected root ownership/mode, target
   path (must be the existing role-managed symlink), absent TLS or CIDR
   restrictions, modified upstream, unexpected Nginx location or version
   of the reviewed vhost structure.
2. Checks working active Nginx and computes SHA-256 of the actual vhost.
3. Defaults to **read-only** and reports only sanitized status and SHA.
4. Requires independent explicit approval and the *exact SHA-256 of
   the same live file* to apply. Mismatch is fail-closed.
5. Atomically inserts exactly one location, runs `nginx -t`,
   gracefully reloads Nginx, then verifies the entire resulting vhost
   differs only by that one location.
6. On failure after replacement, restores only the original Paperless
   vhost and reloads. Raw configuration, keys and logs are never printed.
   Rollback uncertainty is reported separately.

The change **does not** alter the shared `location /` or the 120-second
default for all other routes.

## Operate from bp-controller

Work from a clean, isolated checkout of the feature branch. Run static
regressions before invoking any live audit:

```bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-paperless-chat-proxy"
  BRANCH=fix/paperless-native-chat-nginx-streaming-20261022

  git -C "$BASE" fetch origin "$BRANCH"
  if ! test -d "$WT"; then
    git -C "$BASE" worktree add --detach "$WT" FETCH_HEAD
  fi
  cd "$WT"
  test -z "$(git status --porcelain)"
  git switch --detach FETCH_HEAD

  "$BASE/.venv/bin/python" -m unittest discover -s tests \
    -p 'test_paperless_native_chat_nginx_streaming.py' -v
  "$BASE/.venv/bin/ansible-playbook" \
    -i ansible/inventory.yml \
    -i "$BASE/ansible/inventory.local.yml" \
    ansible/playbooks/repair-paperless-native-chat-nginx.yml \
    --vault-id ai@prompt
)
```

The read-only audit outputs `CURRENT_VHOST_SHA256`,
`AUDIT=READY_FOR_APPLY`, `CHAT_BUFFERING_OFF=NO`, and
`CHAT_READ_TIMEOUT=120s` when still in the diagnosed baseline.
No Nginx changes, service restarts or extra LLM calls occur.

**Separate explicit approval** and exact audited SHA pin required for
first application. Replace the placeholder with the actual reported
fingerprint; never guess or reuse a historical SHA:

```bash
cd "$HOME/bergen-platform-paperless-chat-proxy"
"$HOME/bergen-platform/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$HOME/bergen-platform/ansible/inventory.local.yml" \
  ansible/playbooks/repair-paperless-native-chat-nginx.yml \
  --vault-id ai@prompt \
  -e paperless_chat_proxy_mode=apply \
  -e paperless_chat_proxy_apply_approved=true \
  -e paperless_chat_proxy_expected_sha256=PASTE_CURRENT_VHOST_SHA256
```

After apply:
- Expect `PAPERLESS_NATIVE_CHAT_NGINX=PATCHED_AND_VERIFIED`.
- Rerun default audit to see `ALREADY_APPLIED` with
  buffering OFF and a 300-second chat timeout.
- From an authorized real browser session, ask a short question about
  one known **permitted** family document, and confirm complete answer
  and authorized references. Retest negative parent privacy separately.
- If still failing, use *sanitized* per-request timings and real model
  duration; do not keep raising the timeout indefinitely or relax ACLs.

## Configuration-as-code reconciliation

An **optional** guarded location has also been added to the common
`ansible/roles/nginx_reverse_proxy/templates/internal-proxy-site.conf.j2`
template. It is enabled **only** for
`item.hostname == 'paperless.thebergens.net'` with the explicit per-site
option `native_chat_streaming: true`.

The effective site-local `reverse_proxy_sites` inventory is private and
has **not** been edited here. Before any future execution of
`bootstrap-reverse-proxy.yml` or a generic Nginx-role reconciliation,
add `native_chat_streaming: true` to **only** the existing Paperless
entry, and ensure that the deployed role revision contains the matching
template. Otherwise a generic role rerun may remove the dedicated chat
location. Do not add this property for Bergen-AI or any other site.

No periodic job or automatic restart is introduced.
