# Paperless child native-chat acceptance — separately approved

Scope: **existing** Paperless-ngx 3.3.0 in unprivileged CT126 on
`venombox`. All OCR/document content, IDs, personal users, API credentials
and streamed answers remain outside Ansible output and Git. Changes to
Document, document permissions, the index, Open WebUI and the inbox catalog
are not part of this test.

## Proven prior gates (21 October 2026)

* Independently verified live source receipts and full parent/family document ACL:
  **38 Eltern**, **11 Familie**, **1 active child identity**, **0 parent-visible
  items through archive-wide filtering**, **0 parent single-document allows**.
* Indexed **59/59** current Paperless Documents with the existing local
  Ollama `bge-m3` embedding model. `document_meta` and chunk/vector
  consistency checked: **988 chunks**, **988 vectors**, **0 missing, 0 stale**.
* These results are point-in-time evidence, not permanent protection against
  later ACL or document changes. This playbook checks current live state again.

## Test design

`ansible/playbooks/audit-paperless-native-chat-child-e2e.yml` has
`paperless_native_chat_e2e_mode=audit` by default:

1. Check exact host, unprivileged CT126, backup-included data mount, and
   no incidental ACL/index/configuration approvals.
2. Re-verify actual import receipts, checksums, owner and grants with the
   installed root-owned reconciler. Keep document IDs inside `no_log` facts.
3. With the installed Paperless code, assert each active child has general
   model view, belongs to Familie and Kinder but not Eltern, is not admin/staff,
   sees all family documents, and sees **none** of the protected Eltern scope
   in either the archive-wide filter or single-document view.
4. Check **all** current document modified timestamps and IDs against the
   on-disk SQLite index in `mode=ro`, including chunk/vector totals and
   embedding model name. This audit does not open the live vector-store API,
   create sessions, or call the model.

A separate `live` mode additionally:

1. Uses `django.test.Client.force_login` to create a *temporary* authenticated
   Django session for **each** active real child identity (up to four). This
   is **not** OIDC sign-in and bypasses the credentials/login handshake.
   It does create a short-lived Django session DB row and deletes the session
   on logout; accordingly it requires explicit approval and a recent CT126
   NFS backup.
2. POST `/api/documents/chat/` as the child with a protected parent
   `document_id`: require **403**, no LLM stream invocation.
3. POST with an allowed family `document_id`: require **200** and a real
   streamed answer with a reference to that same family document.
4. POST without document ID (archive-wide): require **200**, an answer and
   document references. Guard the *actual* queryset forwarded to
   `stream_chat_with_documents`: every ID must be in that user's current
   allowed set; **none** may be in Eltern; `unrestricted` must be false.
   Check that reference IDs from the returned metadata trailer are allowed.
5. Fail closed on missing/overlong responses, no references, changed source
   or index scope, unsafe membership, unexpected status or model errors.
   Only aggregate counters and allowlisted failure codes are reported;
   generated answers are never printed.

The live check verifies access filtering at the native Django view and local
streaming route. It cannot prove against all semantic LLM hallucinations or
all future changes, and it cannot attest to the reverse-proxy/OIDC login
boundary. The configured German response **request** is checked, but human
verification of natural German output remains outstanding.

## Run: safe, default audit (no live chat)

Use the isolated feature branch; do not merge or apply a deployment:

```bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-paperless-ai-catalog"
  test -z "$(git -C "$WT" status --porcelain)" || exit 1
  git -C "$WT" fetch origin feat/paperless-native-chat-e2e-acceptance-20261021
  git -C "$WT" switch --detach origin/feat/paperless-native-chat-e2e-acceptance-20261021
  cd "$WT"
  "$BASE/.venv/bin/ansible-playbook" \
    -i ansible/inventory.yml \
    -i "$BASE/ansible/inventory.local.yml" \
    ansible/playbooks/audit-paperless-native-chat-child-e2e.yml \
    --vault-id ai@prompt \
    -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

Expected: `AUDIT=READ_ONLY`, `LIVE_CHAT=NOT_STARTED`,
`CHAT_RELEASE_GATE=BLOCKED` and Ansible `changed=0`.

## Run: **separately approved** live Django-session + local LLM acceptance

Only after the default audit passes and backup evidence is current, the
operator can run the exact same playbook with all three approvals:
`paperless_native_chat_e2e_mode=live`,
`paperless_native_chat_e2e_approved=true`, and
`paperless_native_chat_model_inference_approved=true`.
The site-local `paperless_ai_catalog_verified_backup` must also be true;
it defaults to false in the example configuration. Set this flag to true
**only after personally confirming the backup evidence**. The playbook
independently verifies an NFS backup archive from the past 48 hours; merely
having an archive does not prove a successful restore. These are genuine LLM calls over existing private documents,
not mocks. Tests use bounded output but may have model latency and may
create local inference logs. No password or API key is needed.

```bash
"$HOME/bergen-platform/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$HOME/bergen-platform/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-native-chat-child-e2e.yml \
  --vault-id ai@prompt \
  -e "@$HOME/bergen-platform/ansible/vars/paperless-ai-catalog.local.yml" \
  -e paperless_native_chat_e2e_mode=live \
  -e paperless_native_chat_e2e_approved=true \
  -e paperless_native_chat_model_inference_approved=true \
  -e paperless_ai_catalog_verified_backup=true
```

Expected: `PARENT_DIRECT_DENIED=CHILD_IDENTITIES`,
`FAMILY_DIRECT_WITH_REFERENCE=CHILD_IDENTITIES`,
`ARCHIVE_FILTER_WITH_REFERENCE=CHILD_IDENTITIES` and
`CHAT_RELEASE_GATE=EXTERNAL_OIDC_SMOKE_TEST_REQUIRED`.

Even a passed live result does **not** automatically enable the chat,
alter group ACLs, or release to all children. An authorized operator must
then perform an independent browser/OIDC login as the actual child, verify
that German answers are usable and private parent content is absent, and
repeat after materially changed roles, ACLs, index or Paperless version.
Do not paste private questions/responses, document IDs or browser cookies
into GitHub or chat.

## Operational boundaries

The live test creates/deletes temporary session records, but does not
reclassify, tag or remove `Posteingang`, run index rebuilds, change
permissions, or update the existing five-minute metadata catalog worker.
A failed test leaves the chat release gate blocked, with only sanitized
reason categories available. A full Proxmox restore drill is a separate
backup assurance task.
