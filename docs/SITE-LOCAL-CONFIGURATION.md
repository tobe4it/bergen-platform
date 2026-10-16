# Site-local configuration and privacy boundary

The tracked repository must contain no real home/production DNS names,
site-specific hostnames, internal/public IP addresses, email addresses,
provider record identifiers, directory identities, or credentials. This
applies equally to examples, tests, runbooks, changelogs and release notes.

Use `example.net`, `example.org` or `example.com` for DNS documentation,
`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` for example IPv4,
and generic role names (such as `pve-node` or `proxy-node`). Do not put
real details in Git commit messages, pull-request bodies or tags.

## Required local-only files

- `ansible/inventory.local.yml` supplies actual controller, Proxmox and
  guest hosts and their addresses; the tracked `ansible/inventory.yml` is
  deliberately an empty skeleton. Merge site entries into an existing local
  inventory; **never overwrite an existing local inventory blindly**.
- `ansible/group_vars/all/site.local.yml` supplies local Proxmox API and
  node names, selected inventory host, DNS upstreams, syslog collector,
  LDAP host/DNs and the AI/Paperless proxy hostnames. Copy the tracked
  `site.local.yml.example` as a starting point, then replace placeholders
  in the ignored local file.
- The separate ACME API keys and DNS-zone-specific configurations remain
  in the existing ignored `ansible/vars/*.local.yml` and encrypted
  `ansible/vars/*.vault.yml` files. The Certbot instances on the source
  host continue using their private local root-owned JSON files.

The ignored local files are deliberately **not** installed by Git checkout
or recovered from a repository clone. Preserve them across branch switches,
migrations and backups; protect permissions according to their contents.

## Deployment safety

Site-local hostnames and addresses are never replaced with functioning
example targets in production. A playbook requiring a missing site-local
value must refuse to deploy. After creating site-local files, run the
relevant offline tests, Ansible syntax checks and the existing read-only
preflights before any explicitly authorized apply step. Do not execute
a write-capable playbook just to check that local vars load.

For previously provisioned installations, compare the old site-specific
`ansible/inventory.yml` and group variable files locally, transfer only
required values to ignored local files, and check that Ansible resolves the
same live hosts before merging or deploying this change.

## Historical exposure

A normal sanitization commit cleans only the current tracked tree. Old Git
commits, tags, pull-request diffs and cached clones may still contain
previously committed details. Purging history is a separately approved,
disruptive operation involving a force push, coordination of clones and
releases, and platform-level PR/cache cleanup. Treat any committed
credentials as exposed and rotate them; rewriting history cannot make
leaked credentials safe again.
