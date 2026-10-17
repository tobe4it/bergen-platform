# Nextcloud HTTPS certificate consumer: read-only-first adoption of one
# Certbot deploy hook. No DNS/API writes, certificate reissue, or change to
# the vhost or existing hooks occurs in the default audit.
#
# Keep production identities out of public Git history. Supply approved source
# SSH settings from the existing ignored ansible/vars/mail-tls.local.yml.
#
# Preparation on the Ansible controller:
#
#   cp ansible/vars/mail-cloud-tls.local.yml.example ansible/vars/mail-cloud-tls.local.yml
#   chmod 600 ansible/vars/mail-cloud-tls.local.yml
#   $EDITOR ansible/vars/mail-cloud-tls.local.yml
#
# Put the real cloud hostname, Certbot lineage and existing Nginx paths only
# in that ignored file. Do not change mail services or other Nginx vhosts.
#
# Read-only preflight (no renewals or reloads):
#
#   python3 -m pytest -q tests/test_mail_source_nextcloud_tls_hook.py
#   ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
#     ansible/playbooks/mail-source-nextcloud-tls-hook.yml \
#     -e @ansible/vars/mail-tls.local.yml \
#     -e @ansible/vars/mail-cloud-tls.local.yml --syntax-check
#
#   ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
#     ansible/playbooks/mail-source-nextcloud-tls-hook.yml \
#     -e @ansible/vars/mail-tls.local.yml \
#     -e @ansible/vars/mail-cloud-tls.local.yml
#
# Expected for an existing precisely matching manually installed hook:
# ALREADY_MANAGED; no changes. For an absent hook: READY_TO_CREATE.
# Unknown hook content, unexpected symlinks/ownership, mismatched certificate
# paths, or an invalid Nginx configuration cause a hard failure.
#
# Only if a hook is MISSING and reviewed, install with explicit opt-in:
#
#   ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
#     ansible/playbooks/mail-source-nextcloud-tls-hook.yml \
#     -e @ansible/vars/mail-tls.local.yml \
#     -e @ansible/vars/mail-cloud-tls.local.yml \
#     -e mail_cloud_tls_hook_apply=true
#
# The hook is tightly scoped by RENEWED_LINEAGE. On successful renewal of
# only that lineage, it runs nginx -t then systemctl reload nginx. Its
# installation does NOT immediately reload Nginx. An existing hook is never
# overwritten, even with apply enabled.
#
# Operator acceptance on the source, after reviewing the hook path:
#
#   sudo sh -n /etc/letsencrypt/renewal-hooks/deploy/EXAMPLE_HOOK
#   sudo env RENEWED_LINEAGE=/etc/letsencrypt/live/unrelated \
#     /etc/letsencrypt/renewal-hooks/deploy/EXAMPLE_HOOK
#
# Optionally execute the hook with the actual lineage to verify the reload
# (this DOES reload Nginx). Use a separate explicit operator decision, not
# the read-only playbook.
#
# To verify local TLS without switching public DNS:
#
#   curl --noproxy '*' --resolve cloud.example.invalid:443:127.0.0.1 \
#     -I https://cloud.example.invalid/
#
# A Nextcloud maintenance response HTTP 503 and x-nextcloud-maintenance-mode: 1
# is normal before cutover, provided TLS validates. Do NOT disable maintenance
# or change public A/AAAA records as part of this hook-only operation.
#
# Passing Certbot renewal dry runs proves the DNS-01 renewal mechanism but
# does not prove a future scheduled production renewal plus reload. Observe
# the first actual renewal and check the served certificate fingerprint.
