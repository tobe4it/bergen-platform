# Bergen-AI LXC 110 / Ollama model expansion

Track alongside Issue #113 / Draft PR #114. This branch is a separate
hardware/model preparation and does not enable Paperless AI, public
document chat, embeddings or parental RAG.

## Known state / no assumptions

The established host is venombox: AMD Ryzen AI 9 HX 370, Radeon 890M,
64GB physical RAM. The known LXC 110 bergen-ai is unprivileged with
16 GiB RAM and 2 GiB swap; LXC 126 bergen-paperless is also
unprivileged. On 2026-10-19 the existing LXC 110 Ollama API reported
gemma3:4b, llama3.2:3b, qwen3.5:9b, qwen3:0.6b, qwen3:8b.
These facts do NOT establish current GPU passthrough, Ollama GPU offload,
available model storage, current Paperless Podman networking or host RAM
headroom.

## Chosen install list

Initial: qwen2.5:14b-instruct-q4_K_M (9GB weights),
mistral-nemo:12b (7.1GB) and **bge-m3:latest** (~1.2GB,
embedding only, no RAG activation). Optional later: llama3.1:8b (~5GB).
The exact `bge-m3:latest` tag matters: the Ollama inventory stores
that canonical model name; `bge-m3` without a tag would otherwise
be repeatedly flagged as missing.
Special approval: qwen2.5:32b-instruct-q4_K_M (20GB download) after
memory, storage and performance proof. Coder model not needed for
document tagging. Quantized weight size is NOT peak RAM including
KV cache. A 128k advertised context is not an active efficient
runtime window under the current LXC limits.

The model planner uses conservative rounded download budgets plus
15 GiB headroom. It never deletes an installed model or enables
Ollama network exposure. A download transmits no document contents,
but contacts the model registry and writes downloaded files.

## Step 1 – hardware audit, NEVER restart or change resource settings

On bp-controller as ansible:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    WT="$HOME/bergen-platform-ollama-hardware"
    cd "$BASE"
    git fetch origin feat/bergen-ai-ollama-hardware-models-20261019
    if test -e "$WT/.git"; then
      cd "$WT"
      git switch --detach FETCH_HEAD
    else
      test ! -e "$WT"
      git worktree add --detach "$WT" FETCH_HEAD
      cd "$WT"
    fi
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-bergen-ai-ollama-hardware-readonly.yml \
      --vault-id ai@prompt
    )

This audits exact guest hostname/unprivileged status, current LXC memory,
cores, host RAM availability, GPU device major/minor and GID for
/dev/dri/renderD128 and /dev/kfd both on host and inside guest,
plus actual model directory free GiB. Output is sanitized.

Never run the older generic configure-lxc-gpu playbook with its
historic group ID values without reviewing actual current device
mappings. The generic suggested cgroup device major 511 is not a
safe universal value for KFD. Do NOT switch either LXC to privileged.
Do NOT blindly assign 48 GiB on a 64-GB host running other LXCs.
Use measured free RAM / ARC before a separate, maintenance-window
increase to 24 or 32 GiB. Paperless normally requires no GPU.

## Verified live hardware evidence: 2026-10-19

User-run read-only audit completed with 7 successful tasks, changed=0:
- Ryzen AI 9 HX 370 confirmed, 61,894 MiB host RAM / 49,919 MiB available.
- LXC 110 16,384 MiB RAM, 2,048 MiB swap, **18 cores**, unprivileged;
  GPU passthrough absent. The historical bergen-ai.yml says 8 cores:
  avoid clobbering current production CPU configuration.
- LXC 126 4,096 MiB RAM, 2 cores, unprivileged. Leave unchanged.
- Host renderD128 char major/minor 226:128 GID 993;
  host KFD char major/minor 511:0 GID 993.
- Neither device currently appears inside LXC 110.
- 74.8 GiB free model storage, five installed models, loopback API OK.

### Stage GPU readiness separately, read-only

Before touching resource configuration, use the new playbook:

    (
    set -euo pipefail
    cd "$HOME/bergen-platform-ollama-hardware"
    BASE="$HOME/bergen-platform"
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-bergen-ai-gpu-stage-readonly.yml \
      --vault-id ai@prompt
    )

It validates that native PVE dev0/dev1 slots and the current memory baseline
are unused, confirms actual Ollama UID and render GID inside the guest, and
requires the already measured exact AMD host device major/minor values.

The subsequent *independently approved* playbook is
ansible/playbooks/stage-bergen-ai-ollama-gpu-resources.yml.
It changes ONLY existing unprivileged LXC 110: native Proxmox dev0 for
/dev/dri/renderD128, dev1 for /dev/kfd, each owned by the existing Ollama
UID and guest render GID with permissions 0660; and RAM limit to 32 GiB.
Unlike historical manual cgroup/idmap guides it never changes privileges,
subgid or idmap. A root-only original LXC configuration is saved at
/var/lib/bergen-platform-recovery/ollama-gpu/lxc110-pre-gpu.conf
(0600, never overwritten). A partial failure requires manual review
against this backup, NOT an unexamined container restart.

Stage requires explicit bergen_ai_gpu_stage_approved=true and
bergen_ai_gpu_stage_config_backup_approved=true, after the audit.
It does **NOT** restart LXC 110; a separate scheduled outage and
post-reboot device and GPU-inference checks are required. This change
does not enable Paperless, embeddings, RAG or any new network listener.

Native PVE device passthrough is documented at:
https://github.com/proxmox/pve-docs/blob/master/generated/pct.1-synopsis.adoc
## Post-stage incident: 2026-10-19, exact verification repaired

The operator applied the dedicated GPU/32-GiB staging playbook to LXC 110.
The protected preimage was created, native PVE dev0/dev1 values were written
and memory limit increased. The **old final assertion failed** only because
it expected `dev0: /dev/dri/renderD128` while `pct config 110` actually renders
`dev0: path=/dev/dri/renderD128,uid=999,gid=992,mode=0660`.

Read-only proof supplied by the operator:

    cores: 18
    dev0: path=/dev/dri/renderD128,uid=999,gid=992,mode=0660
    dev1: path=/dev/kfd,uid=999,gid=992,mode=0660
    hostname: bergen-ai
    memory: 32768
    swap: 2048
    unprivileged: 1

The original protected config retains memory 16384, 18 cores, 2048 swap,
unprivileged=1 and no dev0/dev1. The **Stage playbook is not repeatable**
after the protected preimage exists. NEVER rerun it just to get a green recap.

The fixed Stage assertion now validates the actual full Proxmox device lines
including `path=`, uid 999, gid 992 and mode 0660. A new standalone
read-only `audit-bergen-ai-gpu-staged-readonly.yml` verifies the **complete**
actual LXC config against the 0600 preimage. The comparison fails closed
if any unplanned field has changed, or either GPU device has the wrong
path/uid/gid/mode. It also verifies the guest is running.

Before any restart, on bp-controller refresh the separate hardware worktree
and run only the new read-only poststage audit:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    git fetch origin feat/bergen-ai-ollama-hardware-models-20261019
    git switch --detach origin/feat/bergen-ai-ollama-hardware-models-20261019
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-bergen-ai-gpu-staged-readonly.yml \
      --vault-id ai@prompt
    )

Expected: `AUDIT=READ_ONLY`, `STATUS=EXACT_STAGE_ONLY`,
`LXC110_OTHER_CONFIG=UNCHANGED_FROM_PREIMAGE`, `CHANGED=False`,
`RESTART_PERFORMED=NO` and no failures. If not, stop and inspect manually.

**Only after a passing audit and separate outage approval:** coordinate a
restart of LXC 110 (interrupts Open WebUI and Ollama), verify both device
nodes exist with correct ownership inside the guest and Ollama local API
is healthy, then run bounded synthetic inference and inspect Ollama's
GPU/CPU placement. Merely mounting devices does not prove GPU execution.
Paperless and other LXCs must not be restarted as part of this change.
### Post-stage audit runtime assertion correction (2026-10-19)

The full original-vs-staged config comparison passed live, including the
32-GiB ceiling and exact two native PVE device assignments. Its last
assertion, checking `pct status 110`, then failed because the expression
containing `'status: running'` was not quoted as a **YAML scalar** and
was parsed as a mapping, which Ansible rejects as a conditional.
No LXC/GPU/host config was changed by this read-only audit.

Fix: quote the **whole** `assert.that` expression:

    - "bergen_gpu_guest_runtime.stdout | trim == 'status: running'"

Additional regression tests now reject any non-string `assert.that`
entry in all PR #115 GPU playbooks, not only this one. The older
CI syntax check did not detect this runtime typing error.

Do not set `ALLOW_BROKEN_CONDITIONALS`, do not repeat the stage
operation, and do not restart LXC 110 until the corrected full
read-only pre-restart audit returns `STATUS=EXACT_STAGE_ONLY`,
`LXC110_RUNNING=YES` and `failed=0`.
## Step 2 – audit model download needs, still ZERO writes

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/manage-bergen-ai-ollama-models.yml \
      --vault-id ai@prompt
    )

The default requests Qwen2.5 14B, Mistral NeMo 12B and the BGE-M3 embedding model only. Downloading BGE-M3 does **not** start any Paperless embedding jobs or create an index. An explicit
operator decision is required before any model pull.

## Step 3 – deliberate download, only after good disk/resource plan

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/manage-bergen-ai-ollama-models.yml \
      --vault-id ai@prompt \
      -e bergen_ai_models_mode=apply \
      -e bergen_ai_models_approved=true \
      -e bergen_ai_models_download_window_approved=true
    )

This stages only three reviewed local tags (including BGE-M3). A 32B download additionally
requires bergen_ai_models_large_approved=true and a separately specified
model list. Do not use the additional flag before a 32B resource test.
No LXC restarts or application writes are part of model download.

## Separate later change gates

GPU drivers: Official Ollama ROCm7 support lists Ryzen AI 9 HX 370
but the actual container driver/runtime and devices require verification.
Ollama Vulkan can be an alternative. Do not assume GPU inference
solely because /dev/dri exists. A /api/ps check under bounded
synthetic inference must establish CPU/GPU placement.

Ollama listener/firewall: the existing Ansible role defaults to
0.0.0.0:11434 and a 30m keep-alive, but only the running configuration
is authoritative. No 24h keep-alive or unrestricted WAN/LAN opening.
Ollama has no native auth on its HTTP listener. Allow Paperless's
specific guest only after testing the route.

Paperless: global AI and embeddings remain OFF. Native title,
correspondent, tags and document type cataloguing with inbox review
is handled separately by Issue #113 / Draft PR #114.
Parent-only RAG and revocation remain withheld.

Official references:
https://docs.ollama.com/gpu
https://ollama.com/library/qwen2.5:14b-instruct-q4_K_M
https://ollama.com/library/qwen2.5:32b-instruct-q4_K_M
https://ollama.com/library/mistral-nemo:12b
https://ollama.com/library/bge-m3
