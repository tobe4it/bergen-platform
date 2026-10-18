# Bergen-AI ↔ Paperless: OIDC-linked document ACL audit

Draft follow-up to PR #108 identity boundary (https://github.com/tobe4it/bergen-platform/pull/108).
PR #63 remains the main Paperless-AI integration design; Issue #98 covers safe groups.

## Confirmed baseline, 18 October 2026

The production read-only identity check passed: AI OIDC accounts 2, Paperless OIDC accounts 3,
matching active email plus OIDC subject candidates 2 of 2; missing, mismatched
and inactive mapped identities 0. Changed=0. One unmatched Paperless account is
not evidence of any Bergen-AI right.

## New limited gate

The playbook ansible/playbooks/audit-bergen-ai-paperless-oidc-acl-sample-readonly.yml
first imports PR #108's entire identity check, retaining its short-lived HMAC
challenge in protected Ansible facts. It then checks operator-supplied
eight cases: exactly two existing non-staff, non-superuser Paperless OIDC users
against four real documents, with at least one allow and one deny per actor.

For each actor, the helper requires a matching existing allauth subject and
email HMAC from the identical in-memory PR #108 run. The exact configured
single OIDC provider_id is pinned; unknown or multiple OIDC providers fail closed.
An email match alone cannot establish authority. The helper compares each
expected allow/deny with both Paperless permitted_document_ids(view_document)
and an independent authenticated in-process DRF document-detail GET.
16 of 16 checks must pass. No document bodies, metadata, filenames,
user identifiers, claims, actual IDs or API responses are exported.

Only aggregate results or a bounded error code are printed. No database
permissions, groups, documents, services or tokens are changed.

## Private site matrix (fictional example; never use unchanged)

The local, git-ignored path is:
  $HOME/bergen-platform/ansible/vars/bergen-ai-paperless-acl.local.yml

Example YAML:

    paperless_oidc_acl_audit_approved: true
    paperless_oidc_acl_expected_cases:
      - {username: person_a, document_id: 1001, allow: true}
      - {username: person_b, document_id: 1001, allow: false}
      - {username: person_a, document_id: 1002, allow: false}
      - {username: person_b, document_id: 1002, allow: true}
      - {username: person_a, document_id: 1003, allow: true}
      - {username: person_b, document_id: 1003, allow: true}
      - {username: person_a, document_id: 1004, allow: false}
      - {username: person_b, document_id: 1004, allow: false}

Each expected value must be independently reviewed against the intended policy,
not automatically copied from live effective permissions. Choose only users
which are among the already linked Bergen-AI OIDC identities; an extra
Paperless-only identity may not be used as an AI user.

## Controller execution

Create a new worktree for the branch feat/bergen-ai-paperless-oidc-acl-audit-20261018
from the existing repo, then run:

    BASE=$HOME/bergen-platform
    cd $HOME/bergen-platform-ai-paperless-acl
    $BASE/.venv/bin/ansible-playbook \
      -i ansible/inventory.yml \
      -i $BASE/ansible/inventory.local.yml \
      ansible/playbooks/audit-bergen-ai-paperless-oidc-acl-sample-readonly.yml \
      --vault-id ai@prompt \
      -e oidc_identity_audit_approved=true \
      -e @$BASE/ansible/vars/bergen-ai-paperless-acl.local.yml

Ansible Vault is required for the encrypted inventory, not the application
API itself. Do not paste the actual private matrix into chat or GitHub.

## Explicit non-claims

Even 16/16 does NOT prove equal OIDC issuers, secure live AI-user delegation,
AI/RAG query authorization, search/chunk/download/citation/caching isolation,
child permissions, group revocation or existing session/token revocation.
No AI-to-Paperless integration should be enabled on this result alone.
A separately gated broker must enforce Paperless ACLs per query before
model context is assembled, with positive and negative E2E tests.
