# Issue #113 — Bergen Paperless-ngx v3.3.0: native AI inbox catalogue

**State:** versioned implementation in a Draft PR. No production AI config, timer,
document metadata, permissions or archives were changed by the PR. Code review,
live preflight and a one-document trial are mandatory before automatic apply.

## Live initial audit — 2026-10-19 (read-only, PASSED)

Operator executed `audit-paperless-ai-catalog-runtime-readonly.yml`
against the real venombox guests. All 15 tasks passed;
`changed=0 failed=0`.

| Gate | Live result |
| --- | --- |
| Paperless version / configuration | 3.3.0 / 1 singleton row |
| Public AI UI and embeddings | Both OFF |
| Native LLM backend/model/endpoint | NOT_CONFIGURED / NOT_SET / NOT_CONFIGURED |
| Internal local LLM policy | PRIVATE_LLM_ALLOWED=True |
| Inbox tag / all inbox docs | 1 / 33 |
| Family/parent/child groups | 1 / 1 / 1 |
| Active regular parent accounts | 2 |
| Parent-owned inbox documents with OCR | 8 |
| Bergen-AI LXC110 Ollama | Verified guest, healthy loopback API |
| Installed comparison models | qwen2.5:14b-instruct-q4_K_M, mistral-nemo:12b, bge-m3:latest and existing smaller models |

**Not yet verified:** any private network route from the
Paperless *container* in LXC126 to Ollama in LXC110, and the
effective Paperless-native ORM LLM configuration/optimistic
fingerprint. Local Ollama loopback visibility **within LXC110**
does not establish reachability from LXC126. Do not use
`127.0.0.1:11434` as the Paperless endpoint unless Paperless
itself runs the listener; do not copy example addresses into
the real site-local variables.

### Next safe gate: native configuration audit without writes

On bp-controller use the existing AI catalog worktree, updated from
this PR, to run:

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-local-ollama.yml \
  --vault-id ai@prompt
)
~~~

The default action is `audit`, no local vars or approvals required.
Expected: `AUDIT=READ_ONLY`, `STATUS=INSPECTED`,
`AI_UI_ENABLED=NO`, `EMBEDDINGS=OFF`, `CHANGED=False` and
an opaque `CURRENT_SHA256` to gate any later reviewed setting
change. The live network path, backups and approval must be
separately established **before** changing any setting.
## Native ORM configuration audit PASSED (2026-10-19)

The operator executed `manage-paperless-ai-local-ollama.yml` without
extra vars. The default `audit` action returned `AUDIT=READ_ONLY`,
`STATUS=INSPECTED`, `AI_UI_ENABLED=NO`, `EMBEDDINGS=OFF`,
`CHANGED=False`, `ok=9 changed=0 failed=0 skipped=1`. The
optimistic `CURRENT_SHA256` was received; it is **not** an
approval to modify Paperless. No backend, model, endpoint, document
metadata, systemd timer or RAG setting was changed.

### Private Paperless-Podman → Ollama network preflight

Before applying a native LLM configuration, the independent
`audit-paperless-ai-ollama-private-path-readonly.yml` checks the
**actual Paperless Podman application** in LXC126 can reach Ollama
on the verified private address of LXC110. The audit reads
the existing LXC110 interface inventory and Ollama listener
without displaying actual addresses. It requires exactly one
private IPv4 candidate and tests only its `:11434/api/tags` from
within `podman exec bergen-paperless` without proxy or redirects.
No configuration change, model load/inference, document read,
indexing, ACL modification or service restart occurs.

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-paperless-ai-catalog"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-private-path-readonly.yml \
  --vault-id ai@prompt
)
~~~

Expected only if cross-guest access truly works:
`STATUS=PAPERLESS_PRIVATE_PATH_READY` and
`QWEN14_FROM_PAPERLESS_PODMAN=MODEL_PRESENT`. A wildcard
Ollama listener (`OLLAMA_LISTENER=WILDCARD`) requires
separate firewall/exposure review before approval; it is
**not** authority to open additional interfaces.
`REVIEW_PRIVATE_IPV4_SELECTION` indicates multiple or missing
addresses and requires operator selection without broadening
the test. Any `NOT_READY`, `UNREACHABLE`, `UNVERIFIED` or
loopback-only result blocks configuration apply. The audit
never prints the candidate endpoint. Do not substitute an
example IP or use Paperless localhost for LXC110.

**Further gates after a successful path audit:** review actual
network isolation/firewall and verify backups, then prepare an
ignored local vars file with the *actual* private endpoint and
reviewed parent group/domain (keep flags false by default).
The current config fingerprint must be re-observed at the
moment of separately authorized native LLM settings apply.
Global Paperless AI/UI and embeddings/RAG remain OFF.
## Private Paperless → Ollama connectivity verified; firewall review outstanding

On 2026-10-19, the operator successfully ran
`audit-paperless-ai-ollama-private-path-readonly.yml`:
`ok=7 changed=0 failed=0`. The verified LXC126 Paperless Podman
application reached the existing LXC110 Ollama server on its unique
private IPv4 address and observed the exact installed
`qwen2.5:14b-instruct-q4_K_M` tag. No documents, settings or
model files changed. Important classifications:

    STATUS=PAPERLESS_PRIVATE_PATH_READY
    PRIVATE_IPV4_CANDIDATES=ONE
    QWEN14_FROM_PAPERLESS_PODMAN=MODEL_PRESENT
    OLLAMA_LISTENER=WILDCARD
    NETWORK_EXPOSURE_REVIEW=REQUIRED

**A working private route does not demonstrate that outsiders or
unapproved local clients cannot reach Ollama.** In particular,
a wildcard listener with unauthenticated Ollama API port 11434
must have verified access controls. PVE and UniFi policies are
not yet proven; same-VLAN traffic may bypass UniFi routing rules.
Never assume that membership of RFC1918 IP space or a PVE
firewall config file provides isolation.

### Next: read-only Proxmox firewall *configuration* inventory

PR #114 contains a bounded audit of CT110 NIC `firewall=1`
flags, host and cluster firewall config flags, CT firewall rule
file existence and firewall daemon active states. It never
prints IPs, actual rules, or other guest identifiers and it
**always** reports `EXPOSURE_GATE=REVIEW_REQUIRED` because
configuration presence does not establish effective packet
filtering or UniFi policy.

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-paperless-ai-catalog"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-firewall-readonly.yml \
  --vault-id ai@prompt
)
~~~

After the inventory, separately inspect the current Proxmox
filtering rules as well as UniFi/firewall policy for IoT, guest,
DMZ and internal VLANs; verify explicitly that unexpected
clients cannot connect to LXC110:11434. If multiple trusted
guests need Ollama, document exact allowed sources. A UCG rule
does not necessarily control same-VLAN clients. Only after
network isolation and backup/fingerprint gates are approved
may the native Paperless LLM backend/model/endpoint be configured
using its protected, separately approved playbook. No global
Paperless AI, embeddings, RAG or timer activation is authorized.
## Live Proxmox firewall configuration inventory — 2026-10-19

Operator ran `audit-paperless-ai-ollama-firewall-readonly.yml` on
venombox successfully (`ok=7`, `changed=0`, `failed=0`):

| Evidence | Live sanitized classification |
| --- | --- |
| CT110 network interfaces | `ENABLED_ALL_NETS` (`firewall=1` on each) |
| CT110 `/etc/pve/firewall/110.fw` | `ABSENT` |
| PVE cluster firewall config | `NO_CONFIG_FILE` |
| PVE node firewall config | `NO_CONFIG_FILE` |
| `pve-firewall` service | `ACTIVE` |
| `proxmox-firewall` service | `ACTIVE` |
| Effective LXC110 inbound filtering | `NOT_DEMONSTRATED` |
| UniFi rules / intra-VLAN isolation | `NOT_INSPECTED` / `NOT_VERIFIED` |
| Ollama LXC110 listener (prior live probe) | `WILDCARD` |
| Paperless Podman → Qwen14B (prior live probe) | `MODEL_PRESENT` |

**Do not interpret `firewall=1` or active daemons as an access
control.** Missing configuration files do not by themselves
establish global default policy or exact runtime rules; however
there is no CT110-specific allowlist evidence. In particular
the unauthenticated Ollama API may be reachable from unintended
hosts in the same L2 broadcast domain even when UniFi inter-VLAN
routing restrictions exist. IPv6 binding/access and any host nft
filters are not yet validated.

### Next security review (no production mutation)

1. Identify **all intended Ollama clients**: current Paperless
   Podman LXC126, Open WebUI in the same LXC110 using loopback,
   and any additional explicitly authorized application guests.
   Do not assume a broad LAN allow rule is needed.
2. Map the real source/destination interface, subnet, VLAN,
   Proxmox CT110 network bridge, and any UniFi/L3 boundaries
   privately. Never commit internal addresses or identities.
3. Examine effective host firewall packet-filter rules (not
   service state alone), IPv4 and IPv6, and actual allowed
   reachability from a representative unauthorized client.
   Probe only a pre-agreed non-sensitive test client.
4. Design an **explicit allowlist for TCP/11434** limited to
   required clients with a deny for everyone else. Favor guest
   endpoint or Proxmox CT-specific enforcement for clients in
   the same VLAN. Ensure established web UI access / loopback
   Ollama and maintenance are preserved.
5. Any firewall change requires independent operator approval,
   rollback plan and remote-access safety checks. Re-test
   Paperless-to-Qwen reachability and an agreed negative probe.
   Do not open 11434 to all LAN/WAN clients.

**Gate remains BLOCKED** pending effective network policy
evidence and backup verification. Do not invoke the protected
native ORM LLM `apply` or AI cataloguing pilot as a side effect
of this inventory. All global AI, embeddings, RAG and automatic
timers remain OFF.
## Future local Ollama consumers — architecture reservation (2026-10-19)

The operator confirmed that, besides Paperless and local Open WebUI,
**bergen-syslog (existing LXC 120)** should later use Bergen-AI
for analysis of collected infrastructure logs. Other conceivable
consumers include Proxmox operations, isolated IBM MQ lab
diagnostics, BookStack knowledge retrieval, and EVCC/InfluxDB
trend analysis. **Mail/Postfix/Dovecot belongs to the central
syslog data sources, not to a separate future LLM consumer**:
the existing `bootstrap-mail-backend.yml` includes `remote_syslog`,
and `docs/MAIL.md` documents queued TCP forwarding to
bergen-syslog. Verify actual receipt from each currently active
mail gateway/backend separately; configuration alone is not
end-to-end evidence. These are architectural options only,
not active LLM permissions, deployments, jobs or approvals.

**Network and identity policy:**

- In the immediate Paperless trial, allow only the exact verified
  Paperless application source to contact Ollama TCP/11434, after
  negative reachability tests, IPv4/IPv6 and firewall exposure review.
  Open WebUI already co-resides with Ollama and may use loopback.
- Reserve LXC 120 as a *future* client; do not add its source address,
  VLAN or any entire subnet to the current firewall allowlist.
- For additional clients prefer a **dedicated authenticated internal
  inference API gateway** in front of Ollama, with per-workload
  service accounts, rate/compute limits, audit event metadata
  without prompt logging, scoped model permissions and private
  network source restrictions. These controls do not currently
  exist and cannot be inferred from an LLM HTTP listener.
- Do not grant a generic inference endpoint direct access to
  Paperless documents, log files, BookStack pages or their indexes.
  The authorized client retrieves only records allowed by its
  underlying owner/application ACL and sends a bounded request.
  Family wiki and Paperless retrieval must retain per-user ACL
  boundaries; embeddings/RAG remain separately disabled.
- For logs: extend the **existing** `bergen-syslog-analyzer`
  (currently focused on WLAN WPA/EAPOL event types) with a
  separate read-only Postfix/Dovecot detection/correlation module;
  do not create a second log collector. Sources arrive under
  `/var/log/remote/<sender-ip>.log` in LXC120. Use bounded
  time-window queries, deterministic sanitization of secrets,
  mailbox identifiers and other sensitive data, sampling/
  deduplication and no automatic command execution. Verify
  that logs from all relevant current mail gateways and backends
  truly arrive, rather than inferring this from configured
  forwarding. Never ingest the complete unreviewed log stream
  or let LLM suggestions mutate infrastructure.
- For approved future clients, review source identity, runtime
  authorization, retention, concurrency/memory budgeting and
  negative network tests separately. `OLLAMA_LISTENER=WILDCARD`
  remains an **outstanding exposure gate** now.

Thus the Paperless-native AI configuration, one-document metadata
pilot and future syslog use are independent releases; this PR
does not implement a central proxy or authorize any non-Paperless
consumer. Preserve the inbox tag; global Paperless AI UI,
embeddings and RAG remain OFF.
## Next runtime firewall inspection – read-only nft/iptables and IPv6 (2026-10-19)

The previous live configuration inventory showed `firewall=1` on
all CT110 network interfaces, no CT110-specific rule file,
no cluster/node firewall file, and both Proxmox firewall service
names active. This does NOT establish access denial to the
unauthenticated wildcard Ollama API. The previous private-path
audit proved only that Paperless Podman **can** reach Qwen14B.

New `audit-paperless-ai-ollama-runtime-filter-readonly.yml`
reads the **loaded host nftables** rule set (structured JSON),
and optional IPv4/IPv6 legacy iptables-save snapshots, and reads
the LXC110 `ss`-reported AF_INET/AF_INET6 Ollama listeners.
Only sanitized aggregate counts and categories are reported:
observed nft input/forward/prerouting/ingress hook counts,
references to port 11434, mention of veth110 interfaces,
presence of non-link-local IPv6 in the Ollama guest. This
reading itself does not create a new model inference, perform
any outbound network probe or alter network/service state.

On bp-controller:

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-paperless-ai-catalog"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-runtime-filter-readonly.yml \
  --vault-id ai@prompt
)
~~~

**Interpretation:** `NFT_RUNTIME=LOADED` means nft rules are
present/readable, not that a deny rule necessarily applies to
CT110 or TCP/11434. Rule-reference counts can include allows,
denies or non-matching chains; even zero references does not
prove an open port if a parent/default policy denies access.
`IPTABLES_IPV4` and `_IPV6` represent whether the legacy rule
snapshot was readable, not whether those stacks enforce any
specific flow. An IPv6 wildcard socket does not itself prove
a globally routed IPv6 destination, but it requires separate
IPv6 filtering/reachability consideration. The script always
sets `EXPOSURE_GATE=REVIEW_REQUIRED` and `UNIFI_POLICY=NOT_INSPECTED`.

After inspecting these summaries, select an actual **non-authorized
test client** (one on the same VLAN if possible and one in another
VLAN where required). With operator approval, test its ability
to reach `LXC110:11434`; prove Paperless continues to reach the
same endpoint. Determine effective access from real source
addresses and both families before any setting apply.

No role deployment, firewall edit, Ollama listener change,
Paperless configuration change, AI inference or document write
is authorized as part of this inspection. The future
`bergen-syslog` LXC120 client is out of scope for the immediate
Paperless allowlist; a later authenticated inference gateway
can offer separate per-service access controls.
## Live firewall runtime audit and planned negative TCP test — 2026-10-19

Operator completed `audit-paperless-ai-ollama-runtime-filter-readonly.yml`
on venombox: `ok=7 changed=0 failed=0`:

| Evidence | Live status |
| --- | --- |
| nft loaded | `LOADED` |
| Recognized nft base chains / TCP-11434 references | `0 / 0` |
| nft CT110 interface hints | `NOT_OBSERVED` |
| iptables IPv4 and IPv6 snapshot | `AVAILABLE`, `0` rules in each |
| Ollama separate IPv4 listener | `NONE` |
| Ollama IPv6 listener | `WILDCARD` |
| LXC110 non-link-local IPv6 | `PRESENT` |
| Effective 11434 deny / same VLAN isolation | `NOT_VERIFIED` |
| UniFi policy | `NOT_INSPECTED` |
| Exposure gate | `REVIEW_REQUIRED` |

Important: the IPv6 wildcard socket may be dual-stack and accept IPv4,
consistent with the previously successful IPv4 request from the
Paperless Podman container. Presence of a non-link-local IPv6
does **not** prove globally routed IPv6 reachability. Zero recognized
host nft base chains/iptables rules means our tool observed no
applicable explicit enforcement, **not** proof that no other
firewall, bridge, guest, eBPF or gateway control exists.

### One approved negative connect test from bp-controller

Before proposing a CT-specific firewall/ACL change, a single
no-write read-only reachability test is prepared:
`audit-paperless-ai-ollama-negative-client-readonly.yml`.
It verifies current LXC110 identity, discovers the sole private
IPv4 address and at most one non-link-local IPv6 address inside
that guest and cross-checks its IPv4 against inventory
`bergen-ai`. The delegated task executes **only on verified
bp-controller** (not Paperless, and not presently approved
for direct Ollama access), and attempts one TCP connect to
11434 in each address family with a short timeout. No
HTTP request, Ollama inference, arbitrary port scanning,
config changes or guest restarts. Actual addresses remain
protected by Ansible no_log and are never displayed.

At a maintenance-safe time with the operator approving only
this test:

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-paperless-ai-catalog"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-negative-client-readonly.yml \
  --vault-id ai@prompt \
  -e bergen_ai_negative_probe_approved=true
)
~~~

If `IPV4_TCP_11434=REACHABLE`, **an unapproved
management-client source** can reach the Ollama TCP port,
demonstrating broader network accessibility than the currently
reviewed Paperless source. This is a transport-only check;
it cannot by itself prove HTTP API access or full exposure
to all clients. `REFUSED`, `TIMEOUT` or `NO_ROUTE` may
reflect different network controls and only characterize
the tested source/path at that moment, not all untrusted
clients. IPv6 is evaluated independently when a single
eligible guest IPv6 target exists.

**The network approval gate remains `REVIEW_REQUIRED` even
after a negative test**, until expected Paperless access,
the necessary authorized-client list, Proxmox/UniFi rules,
same-VLAN paths and IPv6 paths have been reviewed and any
required network restrictions independently applied and
retested. No automatic changes to Paperless, Ollama,
syslog LXC120, firewall or the timer are authorized.
## Confirmed unauthorized management-client connectivity – 2026-10-19

Operator executed the separate bounded TCP-only
`audit-paperless-ai-ollama-negative-client-readonly.yml`:

    AUDIT=READ_ONLY
    CHANGED=False
    PROBE_SOURCE=BP_CONTROLLER
    IPV4_TCP_11434=REACHABLE
    IPV6_TCP_11434=REACHABLE
    UNAPPROVED_SOURCE_ACCESS=REACHABLE
    OLLAMA_HTTP_REQUESTS=ZERO
    PAPERLESS_CHANGED=NO
    OLLAMA_CHANGED=NO
    EXPOSURE_GATE=REVIEW_REQUIRED
    RECAP: ok=12 changed=0 failed=0

This **proves** a currently unapproved management source can open
a TCP connection to Bergen-AI Ollama port 11434 on IPv4 and IPv6.
The previous Paperless Podman positive probe still proves approved
service-path reachability. It does **not** prove any WAN exposure
or successful HTTP/model requests from bp-controller, since the
negative probe made **no HTTP requests**.

**Hard gate: BLOCKED**. Do not configure Paperless's native LLM
endpoint/model, turn on AI UI, embeddings/RAG or schedule the
cataloguer until host/CT-network policy is designed, explicitly
approved, applied with rollback safeguards, and both approved
positive and non-approved negative access are retested.

Operator also reserved `bergen-syslog` LXC120 for **future**
local inference behind a service-authenticated gateway, including
already-centralized Postfix/Dovecot data sources. It is not a
present allowlist recipient. In the first release, only the
reviewed Paperless container client and local Open WebUI loopback
access should be authorized.

Next: inspect **real** CT110/CT126 PVE bridge and VLAN assignments,
and identify the actual source IP used by the Paperless Podman
outbound connection (Podman NAT, if any) before drafting any
firewall allow rule. UniFi routed policy might not see same-bridge
or same-VLAN traffic. A host or CT-level control, or a separate
authenticated API proxy, must block unauthorized TCP/11434
over both IPv4 and IPv6 while preserving the authorized path.
Any policy implementation or listener change requires separate
approval; there is no blanket permission to restart Ollama,
modify Proxmox firewall or change the host's network topology.
### Next non-invasive preflight: where should access control live?

After the positive *unapproved* bp-controller TCP/11434 test in
both address families, PR #114 includes a scoped read-only
`audit-paperless-ai-ollama-topology-readonly.yml`. It checks
only PVE LXC110 (Ollama) and LXC126 (Paperless): whether each
has exactly one PVE network interface, their same/different
bridge and configured VLAN-tag classification, and whether
the Paperless Podman application's locally chosen IPv4 route
source matches the surrounding LXC126 namespace. The route
test uses UDP socket `connect()` solely to determine the
locally selected source and does **not send datagrams**.

Run from bp-controller in the existing feature worktree:

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-paperless-ai-catalog"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-topology-readonly.yml \
  --vault-id ai@prompt
)
~~~

All data remains local; only category flags are printed. Even a
reported Podman source difference is **not proof of SNAT**, and
the actual **source IP received at LXC110** remains unverified.
Same PVE bridge/tag does not conclusively prove L2 reachability
or that UCG policy can enforce the path; VLAN/firewall details
require operator review. This preflight never authorizes
changes. A future allowlist rule must use the **observed**
real TCP source, preserve localhost Open WebUI, cover IPv4 and
IPv6 and pass Paperless-positive and unauthorized-negative
tests after a separately approved, rollback-safe change.
## Live LXC110/LXC126 topology and conservative VLAN correction (2026-10-19)

Operator's approved **read-only** topology check passed:

    AUDIT=READ_ONLY
    CHANGED=False
    STATUS=TOPOLOGY_CLASSIFIED
    LXC110_NETWORKS=ONE
    LXC126_NETWORKS=ONE
    SAME_PVE_BRIDGE=NO
    SAME_CONFIGURED_VLAN=YES
    PVE_BOTH_NIC_FIREWALL_ENABLED=YES
    PAPERLESS_PODMAN_ROUTE_SOURCE=DIFFERENT_FROM_LXC126_ROUTE
    SOURCE_NAT_EFFECTIVE=NOT_PROVEN
    ACTUAL_LXC110_INBOUND_SOURCE=NOT_DEMONSTRATED
    EXPOSURE_GATE=REVIEW_REQUIRED
    RECAP ok=7 changed=0 failed=0

**Interpretation:** Paperless LXC126 and Bergen-AI LXC110 have
different Proxmox bridges. The old topology script compared
the *presence or absence* of literal `tag` parameters and
incorrectly called two unset parameters `SAME_CONFIGURED_VLAN=YES`.
That is **not evidence of a shared VLAN**, especially across
different bridges. The script has now been corrected to
`NOT_VERIFIED` when either tag is absent, and reports YES/NO
only for two explicit tags. The operator's historical audit
was performed using the older interpretation; no runtime
VLAN reassignment or network change has been made.

The selected Podman **local route source** differs from the
surrounding LXC126 route source. This is compatible with
Podman bridging/SNAT but cannot establish the source address
that Ollama in LXC110 actually sees. The actual firewall
allowlist MUST NOT be based on the original Podman address.

### Optional next gate: observe one real TCP socket's source at Ollama

After explicitly approving one minimal connectivity check during
a quiet Ollama window, the separately gated
`audit-paperless-ai-ollama-observed-source.yml` validates both
guest identities, requires **zero existing** ESTABLISHED
connections on port 11434, starts a single **TCP-only** connection
from the actual Paperless Podman application to verified LXC110
and holds it for eight seconds **without sending HTTP**.
The host inspects the single Ollama-side TCP peer while held,
then confirms the test process finished. No addresses leave
the sanitized task; its report classifies whether the observed
peer matches the LXC126 local route,
the Podman local route or another private IPv4 address.
Nonunique/missing/unexpected sockets fail conservatively
without automatic retry. NAT mechanism is **not inferred**
from the result.

Run only with explicit approval to conduct this one short TCP
observation from Paperless (no model run, no document read):

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
cd "$HOME/bergen-platform-paperless-ai-catalog"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-observed-source.yml \
  --vault-id ai@prompt \
  -e bergen_ai_paperless_source_observation_approved=true
)
~~~

`STATUS=SOURCE_OBSERVED` with
`TCP_PEER_SOURCE_CLASS=MATCHES_LXC126_ROUTE_SOURCE`
would support using the *LXC126 routed egress identity* as the firewall allowlist source, subject to separate effective policy testing; never use Podman's internal private IP as a firewall source merely because it appears in its own namespace. A mismatch
requires separate network/Podman NAT investigation before
a firewall rule can be designed. Either way, the previous
bp-controller **unapproved IPv4 and IPv6** connectivity
must eventually be blocked with a separately authorized
rollbackable policy. `EXPOSURE_GATE=REVIEW_REQUIRED` remains
unchanged. Bergen-syslog LXC120 is reserved for future
authenticated access only; Paperless AI/UI, automatic
cataloging, embeddings/RAG remain OFF.
## Target behaviour

Only **new**, OCR-complete, unreviewed inbox documents belonging to active,
non-staff users of the explicitly reviewed Paperless \`Eltern@...\` group are
eligible for the first release. The exact group is a private deployment
variable; do not hardcode domains in shared code. Children and other groups
are out of scope for the first rollout.

1. Paperless performs its ordinary import/OCR and retains its usual
   \`is_inbox_tag\` tag. Existing import routes, document owner and ACL stay intact.
2. A controlled one-shot worker calls **Paperless 3.3.0's native**
   \`get_ai_document_classification(document, document.owner, None)\` once,
   against its configured *local* Ollama backend, **with embeddings disabled**.
   This uses Paperless's native taxonomy-candidate and owner-permission logic.
3. It conditionally saves **title**, **correspondent**, **document type**, and
   **additive existing tags** (without creating categories).
   - It changes the title **only if** it still equals the original upload
     filename/stem, not after a manual title edit.
   - Correspondent/type are set only if empty; existing values are untouched.
   - Tags are only added; it refuses AI-suggested inbox tags and other
     users' private taxonomy items.
   - Original tags, especially *inbox*, remain. Date, storage path, owner,
     document permissions, original and archive files are NEVER changed.
4. It checks a full snapshot of title, owner, tags, metadata, OCR checksum,
   modified date and other fields **again after the slow LLM call under
   Django select_for_update/transaction.atomic**. Any concurrent user edit,
   changed ownership, removed inbox tag or content drift prevents the write.
5. A **separate** protected on-disk processing journal records pre- and
   post-change document state. Each document is attempted once. Failed,
   interrupted or uncertain writes remain blocked for manual review;
   automatic retries do not overwrite user corrections.
6. The operator verifies the four stored metadata fields in Paperless. Only
   the operator removes the inbox tag. The classical Paperless classifier
   can subsequently train on confirmed documents; this is NOT LLM fine-tuning.

**Limitation:** Titles already differing from the imported filename are not
automatically replaced, even if Paperless's older classifier created them.
This is intentionally safer than overwriting a possible human correction.
The review user can update such titles manually. Unrecognized taxonomy
values are not created, so a correspondent/type can remain unset.

## Approved local model routing (2026-10-19)

The operator selected the following **exact Ollama tags**, independent of
model visibility for Open WebUI users:

| Purpose | Exact Ollama model | Production use |
|---|---|---|
| Paperless inbox metadata classification | `qwen2.5:14b-instruct-q4_K_M` | Selected, awaiting one-document E2E |
| Multilingual quality comparison | `mistral-nemo:12b` | Comparison only; no automatic fallback |
| Future authorization-safe vector retrieval | `bge-m3:latest` | Explicitly **disabled** until separate RAG ACL approval |

The initial LXC-110 inventory (2026-10-19 04:06) predates the later model
installation report. **Recheck the actual Ollama model list and reachability
from Paperless LXC 126** before configuring anything. The exact
`qwen2.5:14b-instruct-q4_K_M` tag must be returned by the server which
Paperless can reach. Do not silently switch to a model from an older inventory.
Only one inference model should be loaded for the first E2E pilot to avoid
unreviewed memory pressure. Using the selected qwen2.5 text-only model does
not require embeddings and is compatible with the intended OCR-text route.

## Architecture

- Paperless 3.3.0 remains the source of truth for documents, OCR, metadata
  and rights.
- One shared local Ollama HTTP server hosts a separately configured
  Paperless model. This does **not** require Open WebUI user model access.
- We use Paperless's **native AI classifier** inside the installed Django
  application, but **not** the native "Apply AI Suggestions" workflow action,
  because its single overwrite switch cannot protect human-authored titles
  and other existing fields independently.
- The bounded five-minute systemd timer runs on **venombox** and calls
  \`pct exec 126 -- podman exec bergen-paperless\`. It is independent of
  family OIDC sync, Paperless RAG and Open WebUI.
- Metadata suggestions may consult Paperless's Tantivy similarity search
  with the actual document owner's rights. No new embedding/vector index
  is configured.
- Documents without recognized owner, with no valid inbox tag, less than
  30 characters of OCR text, versioned documents and non-parent-owned
  documents are **skipped**, left in inbox for manual review.

## Safe rollout sequence on bp-controller

Existing main inventory/vault stays in place; work in a **separate Git
worktree** to avoid the known untracked Paperless files in main:

~~~bash
(
set -euo pipefail
cd "$HOME/bergen-platform"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
test ! -e "$HOME/bergen-platform-paperless-ai-catalog"
git worktree add --detach \
  "$HOME/bergen-platform-paperless-ai-catalog" FETCH_HEAD
)
~~~

On subsequent branch updates use \`git fetch\` plus
\`git switch --detach FETCH_HEAD\`, never \`git worktree add\` again.

Copy the example into the *existing ignored local vars area* and edit it
locally without pasting site values into GitHub or chat:

~~~bash
BASE="$HOME/bergen-platform"
install -m 600 \
  "$HOME/bergen-platform-paperless-ai-catalog/docs/examples/paperless-ai-catalog.local.yml.example" \
  "$BASE/ansible/vars/paperless-ai-catalog.local.yml"
~~~

### 0a — One-command inventory with no local variables (run FIRST)

The new `audit-paperless-ai-catalog-runtime-readonly.yml` reads only
the expected LXC 126 Paperless/Django installation and loopback Ollama
`GET /api/tags` inside the expected LXC 110. It reports aggregate
inbox/OIDC counts, effective AI model status and local Ollama model
names. No document IDs, users, group names, OCR content or IP addresses
are printed. No configuration file or document is written.

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$BASE"
git fetch origin feat/paperless-native-ai-inbox-catalog-20261018
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
  ansible/playbooks/audit-paperless-ai-catalog-runtime-readonly.yml \
  --vault-id ai@prompt
)
~~~

**If `OLLAMA_LOOPBACK_API=UNREACHABLE`**, the model could still be hosted
elsewhere or the service may not run. Do not invent an endpoint; inspect
the private Bergen-AI service inventory in a separate audited step.
If `PARENT_GROUPS=0` or `ACTIVE_PARENT_ACCOUNTS=0`, do not bypass
the OIDC/ACL gate by treating staff accounts as regular parents.

### 1 — Read-only Paperless runtime preflight

Choose the reviewed Paperless parental group, private Ollama endpoint and
**already installed** Ollama model in the ignored vars file. Keep all
approval flags false and \`paperless_ai_catalog_mode: audit\`.

~~~bash
(
set -euo pipefail
cd "$HOME/bergen-platform-paperless-ai-catalog"
BASE="$HOME/bergen-platform"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-inbox-catalog.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
~~~

Expected: \`AUDIT=READ_ONLY\`, \`CHANGED=False\`. The status may initially be
\`AI_CONFIG_NOT_READY\`. **Do not apply** until \`STATUS=READY\`. Check
actual Paperless model availability, global AI UI **disabled**, that the Ollama endpoint
is reachable *from inside the Paperless guest*, that its DNS resolves only to
private addresses and the embedding backend is **empty**. The native
Paperless \`AIConfig\` may read effective database overrides; environment
configuration alone is not proof.

**Current runtime configuration cannot be established from GitHub.**
Do not guess Ollama's address or assume an image/model is already installed.

### 1a — Independent native Ollama settings (global AI UI stays OFF)

Paperless 3.3.0's native `get_ai_document_classification` and
`AIClient` can be used by our guarded background runner **while
`PAPERLESS_AI_ENABLED=false`**. That avoids exposing native document
chat/other AI UI features to all users, and keeps the embedding index off.

First run the **read-only** configuration audit:

~~~bash
(
set -euo pipefail
cd "$HOME/bergen-platform-paperless-ai-catalog"
BASE="$HOME/bergen-platform"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-local-ollama.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
~~~

The result contains an opaque `CURRENT_SHA256`. After independently
confirming the latest backup and Ollama's local endpoint/model, place the
**observed** hash only in the ignored local YAML file. To configure:

~~~yaml
paperless_ai_catalog_config_action: apply
paperless_ai_catalog_config_approved: true
paperless_ai_catalog_verified_backup: true
paperless_ai_catalog_config_expected_sha256: REPLACE_WITH_OBSERVED_64_HEX
~~~

Re-run the same playbook. The version-pinned ORM transaction changes
**only** `llm_backend=ollama`, the exact model and local endpoint. It
creates a protected 0600 preimage for configuration rollback; it never
enables global AI/UI/embeddings or touches document content/permissions.

Configuration rollback needs a new audit/current fingerprint,
`paperless_ai_catalog_config_action: rollback`, plus
`paperless_ai_catalog_config_rollback_approved: true`. A changed
configuration aborts instead of overwriting someone else's change.

The upstream v3.3 setting `PAPERLESS_AI_LLM_ALLOW_INTERNAL_ENDPOINTS`
defaults to true but must be effectively enabled; no unreviewed changes
to the existing Paperless environment or service restart are performed.
The worker validates private DNS and the **exact installed model** using
only Ollama's local `GET /api/tags` (no proxies or redirects).
Once `STATUS=READY` on the **worker** audit, proceed to the pilot.

### 2 — Controlled single-document pilot

Select **one** real, pre-reviewed parent-owned document that remains
in inbox and has usable OCR. Set its ID only in the ignored site-local
variables, keep \`batch_size: 1\`, set \`mode: preview\` and confirm a
positive \`ELIGIBLE_SAMPLE\`.

Before any write, independently verify your last PostgreSQL/document
backup, its restoration plan, the Paperless version and a working Ollama
connection. Explicitly set:

~~~yaml
paperless_ai_catalog_mode: apply
paperless_ai_catalog_pilot_ids: [REVIEWED_REAL_ID]
paperless_ai_catalog_approved: true
paperless_ai_catalog_verified_backup: true
~~~

Use the same Ansible command. It invokes **one** LLM classification and a
bounded, concurrency-checked metadata write. Raw IDs, OCR content, title
and LLM response remain behind \`no_log\`; the terminal prints only
summarized statuses. An unchanged inbox tag plus correct metadata must
be manually confirmed in the Paperless UI.

\`REVIEW_REQUIRED>0\`, missing metadata, a changed human title or an
LLM failure must stop further rollout. A failed or interrupted document
is not auto-retried. Inspect it privately.

### 3 — Guarded rollback of the same pilot

Only if the document is still in inbox **and has not been edited after
AI apply**, change \`mode: rollback\` in the ignored vars and explicitly
set \`paperless_ai_catalog_rollback_approved: true\`. Run the same
playbook. The runner compares the document's post-write state exactly
with its protected journal before reverting AI-added metadata and tags.
It never edits ACLs/owner/inbox. If state changed, rollback stops for
manual review instead of overwriting a human correction.

The journal lives at \`/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3\`
in Paperless's existing persisted data mount and has 0600 permissions.
Protect it with the existing data backups and NEVER copy it into Git.

### 4 — Scheduled automatic processing (a separate release gate)

**DO NOT run the timer playbook until the pilot and rollback tests pass.**

Activation installs a dedicated root-only launcher, pinned policy+worker,
protected local configuration, and a systemd timer on venombox. The timer
starts every five minutes, handles a maximum of **one** new inbox document,
does not process pre-existing history, and never clears inbox.

Set \`min_document_id\` to the **highest current Paperless document ID**
measured immediately before activation (not a guessed value), clear
\`pilot_ids\`, confirm the PostgreSQL+document backups and complete the
rollback trial, then explicitly approve:

~~~yaml
paperless_ai_catalog_mode: audit
paperless_ai_catalog_pilot_ids: []
paperless_ai_catalog_min_document_id: REPLACE_WITH_CURRENT_HIGH_WATER_MARK
paperless_ai_catalog_timer_activate: true
paperless_ai_catalog_timer_approved: true
paperless_ai_catalog_pilot_passed: true
paperless_ai_catalog_approved: true
paperless_ai_catalog_verified_backup: true
~~~

Execute \`ansible/playbooks/deploy-paperless-ai-inbox-catalog-timer.yml\`
with the same inventory, Vault ID and ignored vars file. Verify:
\`systemctl is-enabled bergen-ai-catalog.timer\`,
\`systemctl list-timers bergen-ai-catalog.timer\`,
\`journalctl -u bergen-ai-catalog.service\` (only bounded statuses).
Rollback automation activation immediately by disabling this timer; do
not clear or repurpose the processing journal without separate review.

The code enforces the watermark, dedicated adult scope and per-document
journal. **Any unexpected permission, title, OCR, tag or owner change
during classification halts that document for manual review.**

## Known limitations / remaining acceptance gates

- No live execution has happened from this GitHub PR; bp-controller and the
  productive Proxmox shell are NOT accessible from the GitHub connector.
- The initial rollout intentionally excludes child/private child-owned
  documents and pre-watermark historical documents. Add them only through a
  separately audited owner-/group-specific release.
- Manual title changes *before* the worker first inspects a document are
  detected via conservative original-filename equality, not a complete
  user-edit provenance record; ambiguous titles are never overwritten.
- Rollback is only automatic while the document is still in inbox and has
  no modifications after the recorded post-AI state.
- Metadata suggestion reliability and speed must be measured for the
  actual installed model; empty OCR, model timeout/JSON errors, new tag
  proposals and manually pre-edited fields are required regression tests.
- The native local Ollama client requires a separately approved,
  rollbackable ORM setting change; **global Paperless AI/UI stays OFF**,
  embeddings remain disabled, and no service restart is performed.
  No users/groups, document permissions or RAG/document chat are activated. Family group sync (#98) and parent-only live AI→Paperless
  retrieval (#63) remain separate controlled releases.

## Upstream source pinned and reviewed

- \`paperless-ngx/paperless-ngx@v3.3.0\`:
  \`src/documents/workflows/ai.py\`,
  \`src/paperless_ai/ai_classifier.py\`,
  \`src/paperless_ai/matching.py\`,
  \`src/paperless/config.py\`.
- Native suggestions skip blank OCR. The native action has one global
  \`ai_overwrite_existing\` toggle; this implementation does **not** use it
  for unsafe shared-field overwrites.
- Documentation: https://docs.paperless-ngx.com/advanced_usage/ and
  https://docs.paperless-ngx.com/configuration/.
