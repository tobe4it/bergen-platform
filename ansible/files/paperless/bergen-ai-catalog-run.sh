#!/bin/sh
# Managed by Bergen-Platform / Issue #113. Do not edit on the host.
# Uses only the EXISTING confined Paperless guest and native Django code.
set -eu
umask 077
BASE=/etc/bergen-platform/paperless-ai
test -f "$BASE/catalog-policy.json"
test -f "$BASE/bergen_ai_catalog_policy.py"
test -f "$BASE/bergen_ai_catalog_runner.py"
test "$(/usr/sbin/pct status 126)" = "status: running"

# Never print inputs, model prompts, document IDs, metadata or credentials.
# No shell interpolation of site values into command arguments: policy is
# passed on stdin, while versioned source is one literal Python -c argument.
exec /usr/sbin/pct exec 126 -- /usr/bin/podman exec -i bergen-paperless \
  python /usr/src/paperless/src/manage.py shell --verbosity=0 \
  -c "$(cat "$BASE/bergen_ai_catalog_policy.py"; printf '\n'; cat "$BASE/bergen_ai_catalog_runner.py")" \
  < "$BASE/catalog-policy.json"
