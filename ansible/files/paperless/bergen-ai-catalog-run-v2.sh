#!/bin/sh
# Bergen-AI v2. All Inbox documents imported from 2026-10-01 (Berlin).
# Staged separately from the running v1 launcher; no shell interpolated secrets.
set -eu
umask 077
BASE=/etc/bergen-platform/paperless-ai
test -f "$BASE/catalog-policy-v2.json"
test -f "$BASE/bergen_ai_catalog_policy_v2.py"
test -f "$BASE/bergen_ai_catalog_runner_v2.py"
test "$(/usr/sbin/pct status 126)" = "status: running"

exec /usr/sbin/pct exec 126 -- /usr/bin/podman exec -i bergen-paperless \
  python /usr/src/paperless/src/manage.py shell --verbosity=0 \
  -c "$(cat "$BASE/bergen_ai_catalog_policy_v2.py"; printf '\n'; cat "$BASE/bergen_ai_catalog_runner_v2.py")" \
  < "$BASE/catalog-policy-v2.json"
