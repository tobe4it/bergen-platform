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
## Read-only staged audit PASSED on venombox (2026-10-19)

Current reported status:

    AUDIT=READ_ONLY
    CHANGED=False
    STATUS=EXACT_STAGE_ONLY
    LXC110_MEMORY_STAGED=32768_MiB
    LXC110_GPU_STAGED=RENDER_AND_KFD_WITH_UID_999_GID_992
    LXC110_OTHER_CONFIG=UNCHANGED_FROM_PREIMAGE
    LXC110_RUNNING=YES
    RESTART_PERFORMED=NO
    GPU_COMPUTE_VERIFIED=NO

Play recap was `ok=9 changed=0 failed=0`. All guarded resource
changes are staged, not yet proved active inside the guest.

### Independently approved GPU maintenance reboot (downtime required)

The additional playbook
`ansible/playbooks/restart-bergen-ai-gpu-approved.yml` re-checks
the exact protected full-configuration preimage (not just a device
substring), insists the guest is already running, and requires TWO
explicit acknowledgement flags for the LXC110 service interruption.
It does NOT touch LXC126 or reboot the Proxmox host. Inference is not
run by this playbook. On return it demands running LXC110, the exact
character-device nodes and ownership/mode, `memory.max` 32GiB,
the local Ollama service and API and all three new model tags.

At a suitable maintenance window on bp-controller:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    git fetch origin feat/bergen-ai-ollama-hardware-models-20261019
    git switch --detach origin/feat/bergen-ai-ollama-hardware-models-20261019
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/restart-bergen-ai-gpu-approved.yml \
      --vault-id ai@prompt \
      -e bergen_ai_gpu_reboot_approved=true \
      -e bergen_ai_gpu_reboot_downtime_approved=true
    )

Expected: `STATUS=GPU_POSTBOOT_READY_FOR_SYNTHETIC_INFERENCE`,
`GPU_COMPUTE_VERIFIED=NO`, no failures. The first approved
reboot causes short local Ollama + Open WebUI downtime. Other
services are not restarted.

### Independent read-only GPU postboot verification

If the reboot playbook succeeded, or to check afterward without
a second reboot, run:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-bergen-ai-gpu-postboot-readonly.yml \
      --vault-id ai@prompt
    )

The result `STATUS=READY_FOR_SYNTHETIC_INFERENCE` proves the GPU
nodes are accessible to the Ollama account, the local API is
running and 32GiB LXC memory limit is effective. It does **not**
prove that any model executed on GPU. Next: separately benchmark
one tiny synthetic Ollama request while inspecting processor
placement with `ollama ps` or `/api/ps`.

### Failure discipline

If the reboot or postboot audit fails, **do not rerun the reboot**.
Do not run the pre-reboot rollback playbook after reboot has begun,
because its approval text and assumptions are specifically
pre-restart. Examine PVE task/runtime state and LXC110 service
read-only; any subsequent stop/start or configuration changes
are an incident-level operator decision. Retain the protected
source configuration preimage and do not clobber unrelated LXC
settings. In a failed guest-boot situation, recovery may require
removing only the newly added GPU device nodes and returning the
RAM limit to 16GiB, followed by a reviewed restart, but not an
automatic blind rollback.
## Incident: first GPU-enabled LXC110 reboot did not pass strict readiness

19.10.2026, operator output after running the separate approved reboot
playbook: the single `pct reboot 110` task reported a change, then
all 24 strict postboot readiness retries failed; the subsequent
`GPU_REBOOT_POSTBOOT_NOT_READY_MANUAL_RECOVERY_REQUIRED` assertion failed.
Recap was `ok=10 changed=1 failed=1`. The output alone **cannot establish**
whether the guest failed to start, a device was not created, Ollama was
inactive, a model tag was missing or the strict memory.max test failed.
The latter check compares `/sys/fs/cgroup/memory.max` to exactly
34359738368 bytes; cgroup namespace views can vary and must be
observed rather than guessed.

**Incident instruction: Do NOT run the reboot playbook again; DO NOT
run the pre-restart rollback script.** No blind recovery.

Instead update this hardware worktree and run **only**:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    git fetch origin feat/bergen-ai-ollama-hardware-models-20261019
    git switch --detach origin/feat/bergen-ai-ollama-hardware-models-20261019
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/diagnose-bergen-ai-gpu-postboot-readonly.yml \
      --vault-id ai@prompt
    )

The incident diagnostic reports separately whether:
- existing unprivileged guest config remains as staged;
- LXC110 is running and `pct exec` can run a bounded guest probe;
- each GPU node exists with correct major/minor and owner/group/mode;
- Ollama systemd unit is active and its local /api/tags responds;
- Qwen14/Mistral12/BGE-M3 are present;
- memory.max inside the guest is exactly 32GiB, `max`, different or unreadable.

No document IDs, document content, private IPs, raw journal lines, Ollama
prompts or secrets are emitted. No reboots, downloads or writes are made.
Do NOT conflate an Ansible task returning `ok` with postboot readiness:
the previous strict probe explicitly used `failed_when: false` to
keep retries alive and returned `NOT_READY` or `UNVERIFIED`.
Once independent causes are known, design a targeted repair and a
separate re-verification. No subsequent service restart without review.
## Host-side memory validation after successful GPU postboot diagnosis

Operator-run postboot diagnostic PASSED with `ok=7 changed=0 failed=0`: 
the LXC110 config matches the staged settings; guest running; GPU
renderD128 (226:128) and kfd (511:0) exist and are correctly owned
UID=999, GID=992, mode 0660 and usable by Ollama. The service is
`active`, its local API responds and Qwen2.5 14B/Mistral Nemo 12B/
BGE-M3 are present.

The **only** mismatch is guest `/sys/fs/cgroup/memory.max` reporting
`max` instead of 34359738368 bytes. A cgroup-namespace view may
not show the parent where the host actually enforces Proxmox's
configured `memory: 32768`. Do not interpret that guest `max`
alone as a missing limit and do not reboot or roll back.

To validate actual host-side enforcement, run the separate read-only
`audit-bergen-ai-gpu-host-memory-readonly.yml`. This uses
`lxc-info -n 110 -p -H` to locate the guest init process's **host**
PID, reads `/proc/<pid>/cgroup` and the cgroup-v2 `memory.max`
from the leaf up through parent cgroups. Reports only whether the
smallest finite ancestor limit is exactly 32 GiB, below, above
or completely absent. It never changes a limit.

On bp-controller:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    git fetch origin feat/bergen-ai-ollama-hardware-models-20261019
    git switch --detach origin/feat/bergen-ai-ollama-hardware-models-20261019
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/audit-bergen-ai-gpu-host-memory-readonly.yml \
      --vault-id ai@prompt
    )

Expected if correctly enforced: `CGROUP_LIMIT_STATUS=EFFECTIVE_32GIB`.
If not, STOP and investigate the host-side cgroup location / active
limit before making any further configuration changes. Only after
a positive live host-side reading may the strict postboot acceptance
gate be revised to use real enforcement rather than the guest namespace
view, and then synthetic GPU-offload inference can be tested.
### First host cgroup audit failed before classification (2026-10-19)

The original host cgroup audit was run read-only and returned
`GPU_HOST_MEMORY_CGROUP_UNVERIFIED` (`ok=3 changed=0 failed=1`).
This did **not** establish absent host RAM enforcement. Its first
implementation required standalone `lxc-info -n 110 -p -H` PID
discovery; that approach can fail with Proxmox's managed LXC runtime.

The updated audit FIRST inspects the exact Proxmox cgroup v2 path
`/sys/fs/cgroup/lxc/110/memory.max` and its ancestor chain,
after confirming `pct config 110` and `pct status 110`.
Only if that expected cgroup is not present will it try PID discovery
as a secondary path. The result identifies `CGROUP_SOURCE` and
`CGROUP_LIMIT_STATUS` without exposing a host PID or raw paths.
No restart or resource changes are necessary. Re-run the read-only
host-memory playbook above and review the result before relaxing any
postboot gate or initiating inference.

## Host cgroup proven and postboot verification repaired (2026-10-19)

After two script-level failures the operator directly inspected the
host with read-only Ansible shell. Output:

    pct status 110 -> status: running
    pct config 110 -> memory: 32768, cores: 18, swap: 2048, unprivileged: 1
    CGROUP_V2=YES
    /sys/fs/cgroup/lxc/110/memory.max -> 34359738368
    lxc-info -n 110 -p -H -> numeric host PID

Thus the exact Proxmox LXC110 memory cgroup has a hard 32-GiB
`memory.max` bound. The earlier missing proof came from a
**test implementation defect**: it traversed to the cgroup-v2
filesystem **root** and demanded `/sys/fs/cgroup/memory.max` there.
Under Linux cgroup v2 the root cgroup need not expose memory.max;
that resource-control file belongs to non-root cgroups. The fixed
host audit stops at root instead of demanding a root memory.max.
Regression tests cover missing root memory.max, a leaf reporting max
with finite parent, and real above/below/absent bounds.

The existing postboot audit is also repaired. It now checks the
**actual host** `/sys/fs/cgroup/lxc/110/memory.max` as the memory
enforcement gate instead of mistaking the guest cgroup namespace's
`memory.max=max` for unlimited physical memory. The runtime
readiness classification reports the provenance
`MEMORY_CHECK_SOURCE=PVE_HOST_LXC_110_CGROUP`.

### First synthetic Qwen 14B GPU-offload benchmark

Do this only after confirming service/device readiness and at an
operator-approved time with no other Ollama model loaded. The
separate `ansible/playbooks/benchmark-bergen-ai-ollama-gpu-synthetic.yml`
is **not** a read-only audit: it temporarily loads and executes the
already-installed Qwen2.5 14B model in LXC110. It does not modify
container settings, network listeners, files, tags or Paperless.
Input is a short synthetic German instruction; output text is
discarded. It uses `/api/generate` with `num_predict=40`,
`num_ctx=2048`, and `keep_alive=45s`. An `/api/ps` follow-up
reports `size_vram`; positive GPU allocation constitutes evidence
of offload, while zero means CPU-only as reported by Ollama.
Token speed and load time are recorded without exposing content.
The model unloads by its 45s keep-alive (no persistent pinning).

After operator approval on bp-controller:

    (
    set -euo pipefail
    BASE="$HOME/bergen-platform"
    cd "$HOME/bergen-platform-ollama-hardware"
    git fetch origin feat/bergen-ai-ollama-hardware-models-20261019
    git switch --detach origin/feat/bergen-ai-ollama-hardware-models-20261019
    "$BASE/.venv/bin/ansible-playbook" \
      -i ansible/inventory.yml \
      -i "$BASE/ansible/inventory.local.yml" \
      ansible/playbooks/benchmark-bergen-ai-ollama-gpu-synthetic.yml \
      --vault-id ai@prompt \
      -e bergen_ai_gpu_benchmark_approved=true \
      -e bergen_ai_gpu_benchmark_window_approved=true
    )

If `/api/ps` already shows any model loaded, the script aborts
rather than interrupting concurrent Open WebUI/Ollama usage.
If inference is too slow or a driver is missing, it aborts
without attempting a reboot, model download or device reconfiguration.
Report `GPU_PLACEMENT`, `GPU_ALLOCATED_GIB`, `TOKENS_PER_SECOND` and
the final play recap. Only then consider changes to GPU runtime or
Paperless-AI integrations. BGE-M3 availability does not enable RAG.
## First live Qwen14B GPU offload smoke test PASSED (2026-10-19)

Operator reports clean fixed postboot audit:
`STATUS=READY_FOR_SYNTHETIC_INFERENCE`, `LXC110_RUNNING=YES`,
`GPU_DEVICES_ACCESSIBLE=YES`, `LXC110_HOST_CGROUP_LIMIT_32G=YES`,
`OLLAMA_LOCAL_API=OK`, `ALL_THREE_ADDITIONAL_MODELS=PRESENT`.

Then the independently approved synthetic Qwen2.5 14B run completed:

    STATUS=SYNTHETIC_COMPLETED
    MODEL=QWEN2_5_14B_INSTRUCT_Q4_K_M
    TOKENS_PER_SECOND=14.3
    LOAD_SECONDS=7.53
    EVAL_TOKENS=2
    GPU_PLACEMENT=GPU_ALLOCATION_OBSERVED
    GPU_ALLOCATED_GIB=8.44
    MODEL_INFERENCE_COMPLETED=YES
    PAPERLESS_CHANGED=NO
    PVE_CONFIG_CHANGED=NO
    RECAP ok=7 changed=1 failed=0

Ollama `/api/ps` therefore reported positive GPU memory allocation
while a local, document-free prompt was successfully generated.
This establishes **GPU offload allocation**, not necessarily exclusive
execution on GPU. In particular, integrated Radeon 890M uses
shared system memory rather than 8.44 GiB dedicated VRAM.
The 14.3 tokens/sec result is **not a reliable sustained throughput
figure** because only two output tokens were generated. Before
claiming performance or choosing a default classifier, run an
independently approved longer synthetic prompt (at least ~100
generated tokens), compare with Mistral Nemo and observe model
residency/offload under known load.

Do not reboot, re-stage, roll back or change Paperless for this
successful smoke test. Keep RAG/indexing and document AI activation
behind the separate Issue #113 / Draft PR #114 review gates.
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
