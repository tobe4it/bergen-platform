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
a reviewed sample of exactly two existing non-staff, non-superuser
Paperless OIDC users. The balanced profile uses four real documents and
eight cases with an allow and a deny for each user. The optional
`no-private-b` profile uses three documents and six cases, testing a
deny only for account B; it is explicitly marked as limited.

For each actor, the helper requires a matching existing allauth subject and
email HMAC from the identical in-memory PR #108 run. The exact configured
single OIDC provider_id is pinned; unknown or multiple OIDC providers fail closed.
An email match alone cannot establish authority. The helper compares each
expected allow/deny with both Paperless permitted_document_ids(view_document)
and an independent authenticated in-process DRF document-detail GET.
The balanced profile requires 16 of 16 checks; the reduced profile
requires 12 of 12 checks and reports its untested deny coverage separately.
No document bodies, metadata, filenames, user identifiers, claims, actual
IDs or API responses are exported.

Only aggregate results or a bounded error code are printed.
Neither success status is an approval for AI retrieval. No database
permissions, groups, documents, services or tokens are changed.

## Private site matrix (fictional example; never use unchanged)

The local, git-ignored path is:
  $HOME/bergen-platform/ansible/vars/paperless-ai-acl.local.yml

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

## Guided local matrix preparation

The previous historical paperless-acl.local.yml file is not present on
the controller. Do not recreate a matrix by copying current Paperless
allow/deny results. Instead, the following interactive local script builds
the expected ACL **from four independently confirmed document categories**:

- Private document owned by account A: A can read, B must be denied.
- Private document owned by account B: B can read, A must be denied.
- Document explicitly shared with both adults through the Eltern scope:
  A and B can read.
- Document explicitly shared with both accounts through the Familie scope:
  A and B can read.

Only use this guided path if the **two OIDC-linked AI identities are in fact
the two adult Paperless accounts**, each has a suitable genuinely private
document, and there is one distinct currently present document in each
shared category. Otherwise STOP and design a different approved matrix.
These are intended ACL expectations, **not current measured grants**.

On bp-controller, after creating the worktree described below:

    cd "$HOME/bergen-platform-ai-paperless-acl"
    python3 ansible/scripts/prepare_paperless_oidc_acl_matrix.py \
      --base "$HOME/bergen-platform"

The script asks **locally, without echoing input**, for the two exact
Paperless usernames and four real document IDs visible in the Paperless
UI (A-private, B-private, Eltern, Familie). It requires explicit confirmation
that owner/group sharing and intended access were reviewed independently.
It does **not** contact Paperless, read an ACL, use any token, or change a
document. It writes the eight-case YAML only to the protected site-local
paperless-ai-acl.local.yml with mode 0600, **only if the file does not
already exist**; no overwrite or secrets printed. The canonical filename
is intentionally covered by the existing `ansible/vars/paperless*.local.yml`
ignore rule in the **main** working tree as well as the PR branch.

Confirm the produced file exists and has restricted permissions with
`stat -c '%a %n' "$HOME/bergen-platform/ansible/vars/paperless-ai-acl.local.yml"`.
Do not paste its contents into chat or GitHub.

## Partial profile when account B has no private document

Observed on 18 October 2026: account B has **no private documents**.
Do not create or reclassify a production document merely for this test.
The controller's previous private matrix is absent; the guided builder
was interrupted at the impossible B-private document ID.

The builder now supports the explicit option `--profile no-private-b`.
This selects three independently verified, existing documents:

1. Private account A document: A allowed, B denied.
2. Shared adult/Eltern document: A and B allowed.
3. Shared Familie document: A and B allowed.

The resulting matrix has 2 users × 3 documents = **6 sample pairs**;
the Paperless Guardian and DRF checks therefore total **12**, with
**5 expected allow, 1 expected deny**. Account A's ability to be denied
on another person's private document is **not exercised**. The status
`OIDC_LINKED_PAPERLESS_ACL_SAMPLE_LIMITED` and the coverage marker
`PER_ACTOR_DENY_COVERAGE=ONE_ACTOR_UNTESTED` explicitly state this gap.
It must **not** be presented as a complete negative ACL or RAG release test.

Use the existing worktree (do not repeat `git worktree add`):

    cd "$HOME/bergen-platform-ai-paperless-acl"
    git fetch origin feat/bergen-ai-paperless-oidc-acl-audit-20261018
    git switch --detach FETCH_HEAD
    python3 ansible/scripts/prepare_paperless_oidc_acl_matrix.py \
      --base "$HOME/bergen-platform" \
      --profile no-private-b

Only enter existing, independently verified IDs. The tool never
reads current object permissions to decide its expected policy and
writes only one new, git-ignored 0600 matrix after local confirmation.
The ACL audit can be executed later with the unchanged command below.

Do not share the users or document IDs in chat or GitHub. Do not
enable the Paperless AI integration on this partial result.

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
      -e @$BASE/ansible/vars/paperless-ai-acl.local.yml

Ansible Vault is required for the encrypted inventory, not the application
API itself. Do not paste the actual private matrix into chat or GitHub.

## Explicit non-claims

Even 16/16 does NOT prove equal OIDC issuers, secure live AI-user delegation,
AI/RAG query authorization, search/chunk/download/citation/caching isolation,
child permissions, group revocation or existing session/token revocation.
No AI-to-Paperless integration should be enabled on this result alone.
A separately gated broker must enforce Paperless ACLs per query before
model context is assembled, with positive and negative E2E tests.
