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

Initial: qwen2.5:14b-instruct-q4_K_M (9GB weights) and
mistral-nemo:12b (7.1GB). Optional later: llama3.1:8b (~5GB),
bge-m3 (~1.2GB, embedding only, no RAG activation).
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

The default requests 14B Qwen2.5 and Mistral NeMo only. An explicit
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

This stages only two reviewed local tags. A 32B download additionally
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
