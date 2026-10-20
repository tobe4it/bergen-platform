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


## Paperless-first decision while vmbr90 is suspended (2026-10-20)

The operator confirmed that `venombox` has **no independent, tested
console outside SSH**. Consequently, the previously planned
`vmbr90` bridge + secondary CT110/CT126 NIC apply is **suspended**
(Draft PR #119). The 12/12 successful read-only bridge gates are
not a substitute for a recovery path following SSH disconnection.
Do not set a fictional `CONSOLE_VERIFIED_AND_ROLLBACK_AVAILABLE`
attestation.

**Preferred workstream now:** complete the native Paperless-ngx
3.3.0 AI inbox catalogue in this PR using the *existing*
LXC126 Paperless-Podman → LXC110 Ollama connection.

Previously demonstrated, not to be confused with production
authorization:

- Real Paperless-Podman client successfully reached the existing
  private IPv4 Ollama endpoint and saw the exact
  `qwen2.5:14b-instruct-q4_K_M` model.
- Paperless native model/backend/endpoint was
  `NOT_CONFIGURED` at the initial audit.
- The Ollama service listened on wildcard address(es).
  An **unapproved** `bp-controller` source could make a
  TCP/11434 connection over **both IPv4 and IPv6**.
  This remains a demonstrable excessive-exposure condition.
- `firewall=1` or running PVE firewall daemons alone do
  not show enforcement for this route. Distinct bridges and
  ambiguous VLAN tag evidence also prevent assumptions
  about where packet filtering takes effect.
- Existing Paperless OCR/inbox metadata and OIDC parent
  groups were inventoried without changes; CI for this
  Draft PR is green, but no document pilot has run.

**Do not weaken the security gate to proceed faster.**
While the unapproved TCP reachability remains, the native
Paperless LLM endpoint/model `apply`, one-document
catalogue `apply`, global AI UI, embeddings/RAG and the
automatic timer all stay **NOT AUTHORIZED**.
No Proxmox bridge/NIC, guest/host firewall, Ollama listener
change, service restart, or public proxy should be made
through this workstream without its own safety review.

### Next safe operator action: inspect current effective filters, read-only

Run the existing bounded `nft`/iptables/IPv6 inspection
without emitting source addresses or firewall rules:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-runtime-filter-readonly.yml \
  --vault-id ai@prompt
)
```

Inspect the **sanitized** runtime summary before selecting a policy
enforcement point. The earlier negative-client TCP proof cannot be
overridden by a rule-count-only audit; observed source identities
and an actually effective IPv4/IPv6 allowlist require separate proof.
Do not apply host/guest network changes without an operationally
reliable rollback/recovery path.

A separate previously authored, operator-approved TCP-only source
observation (`audit-paperless-ai-ollama-observed-source.yml`)
can later be used in a quiet window to identify the *actual*
Paperless source seen by Ollama. That probe is **not**
implicitly approved by the decision to prioritize Paperless.
Do not invent an allowed source IP from a Podman local route.

After an independently verified access-control design and actual
positive-Paperless/negative-unapproved-client tests, refresh the
read-only Paperless ORM fingerprint, verify Paperless DB+files
backups, configure only the native local LLM setting with
the separate explicit gate, then preview and run **one**
parent-owned inbox document. Keep the inbox tag for human
review; timer activation and any unattended processing
remain later releases.

No production changes performed by this documentation update.

## Operator decision 20.10.2026 – connect Paperless to existing Ollama first

The operator explicitly selected **connecting the existing Paperless native
LLM backend/model/endpoint first**, and restricting the already exposed
Ollama API separately later. This changes the *order of work for the
client configuration only*; it does **not** approve the `vmbr90` Proxmox
network apply, a firewall or Ollama listener change, document classification,
global AI UI, embeddings/RAG, or an automatic catalog timer.

Technical boundary:
- LXC126's real Paperless Podman container **already reached** the existing
  LXC110 Ollama instance and the exact `qwen2.5:14b-instruct-q4_K_M` model.
  The planned first change is **only** Paperless-ngx's existing
  `ApplicationConfiguration` ORM fields `llm_backend`, `llm_model`,
  `llm_endpoint`. It creates no new network interface or API exposure.
- The latest live Ollama security audit (20.10.2026, 10:43) found
  `OLLAMA_IPV6_BIND=WILDCARD`, `OLLAMA_IPV4_BIND=NONE` and
  `EFFECTIVE_TCP_11434_DENY=NOT_VERIFIED`. The earlier explicitly
  unauthorized bp-controller TCP client reached port 11434 over both IPv4
  and IPv6. Deferring access restrictions leaves that known risk unresolved.
- Paperless backend configuration should be restricted to the **exact
  verified private endpoint** reached from Paperless Podman. Do not
  invent a new IP, use localhost in Paperless or rely on documentation
  example `192.168.0.100`.
- An effective Paperless DB+document-file backup, exact optimistic
  `CURRENT_SHA256`, current exact Qwen model reachability and the
  protected preimage mechanism remain required. The earlier CT126
  `RECENT_FILE_METADATA_ONLY` evidence is **not** restore verification.
- Do **not** assert the verified-backup boolean or approval unless they are
  actually true. Never overwrite an existing preimage. No automatic
  writes of document title, correspondent, type or tags are authorized
  by this client configuration decision.

### Staged operator commands (bp-controller)

**1. Reverify the existing Paperless→Ollama path without writes:**

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-ollama-private-path-readonly.yml \
  --vault-id ai@prompt
)
```

**2. Read the *current* native Paperless configuration fingerprint,
still without writes:**

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-local-ollama.yml \
  --vault-id ai@prompt
)
```

Expected audit fields: `AUDIT=READ_ONLY`, `STATUS=INSPECTED`,
`AI_UI_ENABLED=NO`, `EMBEDDINGS=OFF`, a 64-character
`CURRENT_SHA256`, `CHANGED=False`.

**3. Only after independent backup confirmation and reviewed private
endpoint/model:** Edit the ignored controller-local
`$BASE/ansible/vars/paperless-ai-catalog.local.yml` with the actual
private URI/selected model, `paperless_ai_catalog_config_action:
apply`, `paperless_ai_catalog_config_approved: true`,
`paperless_ai_catalog_verified_backup: true`, and the fingerprint
just observed. Then run `manage-paperless-ai-local-ollama.yml`
with the reviewed variables file, as described under '1a' above.
That playbook changes only the three ORM fields. If a backup,
fingerprint or endpoint is not confirmed, **stop before apply**.

**4. Postcheck:** Rerun the ORM configuration audit (without local
apply flags), confirm the existing private-path model and ensure
Paperless global AI/UI and embeddings remain off.
Do not run the document-level `manage-paperless-ai-inbox-catalog.yml`
apply or `deploy-paperless-ai-inbox-catalog-timer.yml` yet.

The security hard gate now explicitly applies to **document-level
processing and unattended use**, while the one-time native connection
configuration can be separately operator-approved with its own safe
backup, model, endpoint and fingerprint prerequisites. The deferred
access restriction remains an open finding and must not be called fixed
or masked by a successful Paperless backend configuration.

## Live follow-up 2026-10-20 10:52 – native endpoint preflight passed

Operator re-ran both independently pinned read-only audits
from the existing PR worktree on `bp-controller`:

```text
audit-paperless-ai-ollama-private-path-readonly.yml
  STATUS=PAPERLESS_PRIVATE_PATH_READY
  OLLAMA_LISTENER=WILDCARD
  PRIVATE_IPV4_CANDIDATES=ONE
  QWEN14_FROM_PAPERLESS_PODMAN=MODEL_PRESENT
  NETWORK_EXPOSURE_REVIEW=REQUIRED
  venombox ok=7 changed=0 failed=0

manage-paperless-ai-local-ollama.yml (default action audit)
  AUDIT=READ_ONLY
  STATUS=INSPECTED
  CURRENT_SHA256=940974cca3becf2fb0d71e54b66437aba1e9c5ca8b8ea01d8071433148c5a7bc
  AI_UI_ENABLED=NO
  EMBEDDINGS=OFF
  CHANGED=False
  venombox ok=9 changed=0 failed=0 skipped=1
```

The initial invocations had a wrong Vault decryption entry;
the subsequently successful runs show the password was correctly
supplied. These are connection/configuration **readiness checks**:
**no** native Paperless LLM backend setting, catalogue metadata,
Proxmox network or Ollama/firewall configuration was changed.

### Operator next steps – no guessed URI or backup attestation

Use `ansible/playbooks/audit-paperless-existing-backend-readonly.yml`
to recheck that the *actual* CT126 rootfs and persistently mounted
Paperless data volume both have backup participation enabled.
This is a configuration-only check, **not** proof a current,
recoverable archive exists.

The currently selected single real CT110 private IPv4
must be obtained locally through the already approved
`venombox` Ansible transport (e.g. `pct exec 110 -- ip -o -4 addr
show scope global`); match the *actual* one reached by
Paperless-Podman, not the example `192.168.0.100`.
Keep internal URI and the real `Eltern@...` group in the
ignored `$HOME/bergen-platform/ansible/vars/paperless-ai-catalog.local.yml`
with 0600 permissions.

Once the **actual current Paperless DB/files backup and a viable
rollback path have been independently checked**, the operator
may choose to set `paperless_ai_catalog_verified_backup: true`
and separately set `paperless_ai_catalog_config_approved: true`,
`paperless_ai_catalog_config_action: apply`, along with
`paperless_ai_catalog_config_expected_sha256` equal to the
live fingerprint observed at approval time.
The prior 10:52 SHA is **historical**; if application state
changes before apply the guarded transaction must reject it.

Apply only `manage-paperless-ai-local-ollama.yml` using the
ignored reviewed variables file. This modifies only
`llm_backend`, `llm_model` and `llm_endpoint`;
it must not set `paperless_ai_catalog_approved` for
document writes or activate any timers.

Afterwards re-run that same playbook with its default
`audit` action (no site local approval variables)
and verify Paperless UI/embeddings remain OFF.
Recheck private Ollama model reachability if needed.
The wildcard unauthenticated TCP/11434 exposure to
bp-controller on both address families **remains unresolved**,
and classification of real documents is still blocked
until its separate, explicit approval and security review.

## Live follow-up 2026-10-20 11:57 – parent-scope catalogue audit

After populating the ignored `paperless-ai-catalog.local.yml` with
the locally observed LXC110 private endpoint, reviewed model, parent group,
and previous read-only configuration fingerprint, the operator validated
the YAML and ran `manage-paperless-ai-inbox-catalog.yml` in
default `audit` mode using the site variables file.

```text
AUDIT=READ_ONLY
STATUS=AI_CONFIG_NOT_READY
PAPERLESS_VERSION=3.3.0
ELIGIBLE_SAMPLE=8
APPLIED=0
REVIEW_REQUIRED=0
ALREADY_RECORDED=0
ROLLED_BACK=0
CHANGED=False
venombox ok=9 changed=0 failed=0 skipped=1
```

**Meaning:** The explicitly supplied Paperless Django parent group
resolved to exactly one group (otherwise the runner fails closed).
Eight matching, OCR-eligible parent-owned inbox documents were
counted in the bounded preview scope; **none was processed**.
`AI_CONFIG_NOT_READY` is expected while the native
`llm_backend`/`llm_model`/`llm_endpoint` have not been set
in Paperless's singleton configuration.

A separate existing-backend read-only audit passed
(`PAPERLESS_ROOT_AND_DATA_MOUNT_BACKUP_INCLUDED=true`,
three services active), but it only verifies that both
filesystems participate in the backup configuration.
Previously discovered recent CT126 `vzdump` metadata
likewise does **not** verify archive integrity, database
consistency, successful restoration, or data recovery.

**Next operator evidence before native ORM connection apply:**
identify an actual current complete CT126 `vzdump`
archive in the expected mounted NFS backup repository,
review its completed backup job and validate compressed
archive integrity without extracting, restoring, or
altering production. Assess database + media/data coverage
and rollback plan. A successful `zstd -t` alone is
not a full restore proof. Do not set
`paperless_ai_catalog_verified_backup: true`
based only on JSON/YAML validity, backup=1, or filenames.

Native LLM client configuration (three ORM fields only)
remains the next separately authorized mutation after
that evidence, using a fresh optimistic
`CURRENT_SHA256`. Document classification, timer,
Paperless global AI UI, embeddings, Ollama listener and
firewall remain unchanged and unapproved in this gate.
The unauthenticated wildcard port exposure is a
known, deferred security task.


## CT126 backup inventory 2026-10-20 11:00 – recent archives, missing same-day result

Operator read actual NFS/Proxmox metadata on `venombox`
without modifying files, stopping services, or altering
the backup schedule. Mounted storage type: `nfs4`.
The five most recent listed CT126 `vzdump` archives were:

| Archive date | Recorded compressed bytes |
| --- | ---: |
| 2026-10-19 03:02 | 1,585,779,616 |
| 2026-10-18 03:07 | 1,573,769,658 |
| 2026-10-17 03:01 | 1,558,860,332 |
| 2026-10-16 03:01 | 1,504,436,666 |
| 2026-10-15 03:03 | 1,492,825,227 |

**No 2026-10-20 archive appeared** in the operator's
most-recent-five listing at approximately 11:00 local,
despite the historically documented daily 03:00
`bergen-paperless-vzdump.timer` schedule. Its cause
is **unknown**: do not infer that systemd ran, that
the backup failed, that the timer is enabled, or
that the archive could not be in another storage.

Archive names, sizes, NFS mount status and `backup=1`
flags are *not* integrity, consistent PostgreSQL
snapshot or full-restore proofs. A successful
`zstd -t` plus a streamed GNU tar listing only
verifies the encoded stream and TAR structure;
it does not test Paperless boot, database recovery,
media completeness or restore authorization.

Operator next action: review the systemd timer and
last job result read-only, then test the **pinned**
19 Oct archive with `zstd -tq` and
`tar --zstd -tf ... > /dev/null`. Avoid
`vzdump`, retention/pruning, test restores in
production or any CT126 stop/restart here.
`paperless_ai_catalog_verified_backup` remains false
until the usable DB/files backup and rollback
plan are independently assessed. The standalone
Paperless-native Ollama endpoint/model/backend apply
and all document processing remain unexecuted.

## CT126 backup incident 2026-10-20 – 03:00 job failed with rc 255

Read-only operator report on `venombox`:

```text
bergen-paperless-vzdump.timer:
  LoadState=loaded
  ActiveState=active
  UnitFileState=enabled
  LastTriggerUSec=Tue 2026-10-20 03:00:02 CEST
  NextElapseUSecRealtime=Wed 2026-10-21 03:00:00 CEST
bergen-paperless-vzdump.service:
  Result=exit-code
  ExecMainStartTimestamp=Tue 2026-10-20 03:00:02 CEST
  ExecMainExitTimestamp=Tue 2026-10-20 06:00:02 CEST
  ExecMainStatus=255
19 Oct archive:
  ZSTD_INTEGRITY=PASS
  TAR_STRUCTURE=PASS
BACKUP_CHECK=COMPLETED_READ_ONLY
```

**Incident:** The scheduled 20 Oct backup returned a failure
after exactly three hours. The timer remained active and
enabled for 21 Oct. An exact three-hour run is suspicious
for a time limit, but `Result=exit-code` alone does
**not** prove a systemd timeout. The IaC template specifies
`TimeoutStartSec=infinity`; inspect the **live**
`TimeoutStartUSec`/drop-ins and bounded job journal
before attributing the cause. The 19 Oct stream and TAR
are intact, but its actual PostgreSQL recovery, document
mount completeness, and full restore are not proven.

**Read-only, privacy-safe first diagnosis (on bp-controller):**

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible" venombox \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  -b -m ansible.builtin.shell \
  -a '
set -eu
echo "=== SYSTEMD EFFECTIVE SERVICE ==="
systemctl show bergen-paperless-vzdump.service \
  -p Result -p ExecMainCode -p ExecMainStatus \
  -p TimeoutStartUSec -p TimeoutStopUSec \
  -p FragmentPath -p DropInPaths
echo "=== BACKUP JOB JOURNAL CLASSIFICATIONS ==="
journalctl -u bergen-paperless-vzdump.service \
  --since "2026-10-20 02:55:00" \
  --until "2026-10-20 06:10:00" \
  --no-pager -o cat | awk '"'"'
  {
    s=tolower($0); n++;
    if(s ~ /timed? out|timeout|time limit|deadline|watchdog/) timeouts++;
    if(s ~ /nfs|stale file handle|server not responding|mount/) nfs++;
    if(s ~ /no space left|enospc|disk full|quota/) space++;
    if(s ~ /permission denied|operation not permitted/) permission++;
    if(s ~ /i\/o error|input\/output error|broken pipe|read-only file system/) io++;
    if(s ~ /zfs|snapshot/) zfs++;
    if(s ~ /oom|out.of.memory|killed process/) oom++;
    if(s ~ /error|failed|fatal|aborted/) errors++;
  }
  END {
    print "JOURNAL_LINES=" n+0;
    print "TIMEOUT_MARKERS=" timeouts+0;
    print "NFS_MOUNT_MARKERS=" nfs+0;
    print "STORAGE_CAPACITY_MARKERS=" space+0;
    print "PERMISSION_MARKERS=" permission+0;
    print "IO_MARKERS=" io+0;
    print "ZFS_MARKERS=" zfs+0;
    print "OOM_MARKERS=" oom+0;
    print "ERROR_MARKERS=" errors+0;
    print "JOURNAL_CLASSIFICATION_ONLY=YES";
  }
  '"'"'
' \
  --vault-id ai@prompt
)
```

This diagnostic prints no raw journal lines, target IPs,
document content or credentials. Marker counts are
**hints**, not precise causes. If all error counts are zero,
inspect exact host-local logs privately before classifying.
Do not restart, reconfigure or manually launch `vzdump`,
alter pruning, or set
`paperless_ai_catalog_verified_backup: true`
based on the latest failure or on archive-structure
checks alone.

The existing native Paperless Ollama route and parent
group audit remain successful (`ELIGIBLE_SAMPLE=8`)
but neither document classification nor the protected
ORM connection apply has been executed.


## Backup job failure diagnosed as outstanding incident (2026-10-20)

Operator's read-only Proxmox check after the NFS metadata inventory:

```text
bergen-paperless-vzdump.timer:
  LoadState=loaded
  ActiveState=active
  UnitFileState=enabled
  LastTriggerUSec=Tue 2026-10-20 03:00:02 CEST
  NextElapseUSecRealtime=Wed 2026-10-21 03:00:00 CEST

bergen-paperless-vzdump.service:
  Result=exit-code
  ExecMainStatus=255
  ExecMainStartTimestamp=Tue 2026-10-20 03:00:02 CEST
  ExecMainExitTimestamp=Tue 2026-10-20 06:00:02 CEST

2026-10-19 CT126 vzdump archive:
  ZSTD_INTEGRITY=PASS
  TAR_STRUCTURE=PASS
  BACKUP_CHECK=COMPLETED_READ_ONLY
```

**Incident:** The enabled Paperless `vzdump` service exited
with failure code 255 at exactly 3 hours on 20 October.
The underlying failure reason is **not established**.
Do not assert a systemd timer timeout: `Result=exit-code`
means the process terminated with nonzero exit code; a
systemd-enforced timeout typically appears as
`Result=timeout`. A backup stop, NFS stall,
quota, `vzdump` error or effective unit override must be
distinguished using job logs and unit runtime metadata.
The archive from the previous date passed stream/TAR
checks only; database recoverability remains unproven.

Before the next night run, investigate with strictly
read-only commands on `venombox`:

```bash
systemctl show bergen-paperless-vzdump.service \
  -p Result -p ExecMainCode -p ExecMainStatus \
  -p TimeoutStartUSec -p RuntimeMaxUSec \
  -p FragmentPath -p DropInPaths
systemctl cat bergen-paperless-vzdump.service
pct status 126
journalctl -u bergen-paperless-vzdump.service \
  --since '2026-10-20 02:55:00' \
  --until '2026-10-20 06:10:00' \
  --no-pager -o short-iso
```

Treat logs as private infrastructure data; redact network
locations, storage paths and any sensitive material before
external sharing. Read the corresponding Proxmox `vzdump`
task log locally if the systemd journal lacks the cause.
Check the current three Paperless services; do not
assume a failed `--mode stop` backup necessarily
restarted the guest. Do **not** manually rerun the
`vzdump` job, change retention, restart CT126, or
disable/edit the timer as a side effect of diagnosis.
Any of those actions require separate operational review.

The 20 October failure keeps
`paperless_ai_catalog_verified_backup=false` and
the native Paperless Ollama ORM config `apply` unexecuted
pending a reviewed recovery/backup verification.
The planned connection already works at TCP/HTTP model
discovery level and is **not** the cause of the
backup failure. All Paperless document metadata, AI
UI, RAG/embeddings, scheduled AI and `vmbr90`
remain unchanged by these audits.


## Live native Ollama configuration apply SUCCEEDED – 2026-10-20 13:05

The operator explicitly accepted the **2026-10-19 CT126 vzdump**
as the rollback reference, confirming no relevant Paperless
changes since then. The compressed archive passed
`zstd -tq` and `tar --zstd -tf` integrity/structure checks;
a full PostgreSQL/document recovery test was **not** performed.
The 2026-10-20 03:00 scheduled backup **failed**
(`Result=exit-code`, status 255); that independent incident
remains open. The oneoff ORM configuration backup acceptance
is not evidence that the failed scheduled backup was fixed.

Operator applied the **separately approved** Paperless native
Ollama settings change from `bp-controller` using:

```text
ansible/playbooks/manage-paperless-ai-local-ollama.yml
paperless_ai_catalog_config_action=apply
paperless_ai_catalog_config_approved=true
paperless_ai_catalog_verified_backup=true (operator oneoff acceptance only)

AUDIT=CONTROLLED
STATUS=LOCAL_LLM_CONFIG_APPLIED
AI_UI_ENABLED=NO
EMBEDDINGS=OFF
CHANGED=True

venombox ok=9 changed=1 failed=0 skipped=1
```

The reviewed site-local configuration selected the
existing private LXC110 Ollama endpoint
(`192.168.20.225:11434`, DHCP at that time) and the
installed `qwen2.5:14b-instruct-q4_K_M` model.
The three intended Paperless ORM fields were
`llm_backend`, `llm_model`, `llm_endpoint`.
The runtime change reported success and no global AI
UI or embedding activation. The guarded apply stores
a private 0600 prechange snapshot for future rollback
provided that its persistence was successful, but
actual rollback has **not** been performed.

**Important distinction:** a write-success status proves
that the controlled Paperless config operation ran,
but the *post-apply effective runtime state* and
the document runner's `STATUS=READY` still require
a **separate live read-only check**. The 13:05 apply
response returns `CURRENT_SHA256=N/A` by design;
refresh the hash before any future setting change.

### Mandatory no-write postchecks

On `bp-controller`, from the existing Paperless-AI
worktree, run:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-local-ollama.yml \
  --vault-id ai@prompt
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-inbox-catalog.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

Expected first result: `AUDIT=READ_ONLY`,
`STATUS=INSPECTED`, `AI_UI_ENABLED=NO`,
`EMBEDDINGS=OFF`, `CHANGED=False`,
a **new** `CURRENT_SHA256`.

Expected second result if the endpoint/model and
parent-owned inbox policies are still valid:
`AUDIT=READ_ONLY`, `STATUS=READY`,
`CHANGED=False`. No document is classified by
either postcheck. If the second result is still
`AI_CONFIG_NOT_READY`, investigate the effective
database settings before any repeat `apply`:
the guarded config snapshot explicitly prevents
blind reapplication.

**Still not authorized:** document-level
`manage-paperless-ai-inbox-catalog.yml` apply,
timer deployment, global Paperless AI UI,
embeddings/RAG, the `vmbr90` network change,
or Ollama listener/firewall modifications.
The broader, unauthenticated TCP/11434 reachability
from `bp-controller` on both address families
remains an acknowledged, deferred security risk.

## Live ORM post-apply audit 2026-10-20 13:08 – INSPECTED

Operator reran `manage-paperless-ai-local-ollama.yml`
with its default read-only `audit` action after the
successful native-LLM configuration apply:

```text
AUDIT=READ_ONLY
STATUS=INSPECTED
CURRENT_SHA256=d1ec58b87da6163b99fca00e5aa144d9a421fbce129312fa84243afc5c2978ea
AI_UI_ENABLED=NO
EMBEDDINGS=OFF
CHANGED=False
venombox ok=9 changed=0 failed=0 skipped=1
```

This is the **post-change** configuration fingerprint,
not a pre-change token; use a new live audit/fingerprint
before any future mutually independent config change.
The result confirms that the native configuration is
readable, global AI UI remains disabled and the embeddings
backend remains off. The `INSPECTED` status alone does
**not** confirm the catalogue worker's effective endpoint
and model, a live inference, or per-document permissions.
No document metadata was changed during the postcheck.

The excerpt preceding this run included an Ansible recap
(`bp-controller ok=5`, `venombox ok=28`) without the
corresponding task details; do not infer its function
or effect from the recap alone.

**Still required now:** run the independently existing
`manage-paperless-ai-inbox-catalog.yml` using the
ignored site-local variables file in unchanged
`paperless_ai_catalog_mode: audit` and confirm
`STATUS=READY` (not `AI_CONFIG_NOT_READY`).
No `apply`, preview mutation, pilot or timer is approved.
The originally observed `ELIGIBLE_SAMPLE=8`
was **before** the native backend configuration,
and must not be assumed to be the new count.

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-ai-inbox-catalog.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

The scheduled CT126 backup failure on 20 Oct and wider
Ollama TCP/11434 IPv4/IPv6 exposure remain separate
open security/operational findings. The operator accepted
the 19 Oct archive for the earlier **config-only** apply;
that does not grant unattended document classification.


## Operator live 2026-10-20 13:12 – catalog worker READY

The first post-apply read-only catalogue-worker audit completed
successfully on the actual Paperless guest after the separate
Ollama native-configuration apply:

```text
AUDIT=READ_ONLY
STATUS=READY
PAPERLESS_VERSION=3.3.0
ELIGIBLE_SAMPLE=8
APPLIED=0
REVIEW_REQUIRED=0
ALREADY_RECORDED=0
ROLLED_BACK=0
CHANGED=False
venombox ok=9 changed=0 failed=0 skipped=1
```

**Interpretation:** The existing Paperless-native AI client now
matches the reviewed private Ollama endpoint and installed Qwen
model, and the operator's exact Paperless parent group exists.
Eight OCR-eligible inbox documents appear in the bounded
read-only set. No model classification or document write was
performed by this audit. The catalogue timer is still OFF;
no one-document pilot has been approved or run yet.

**Next safe gate:** The operator selects **one actual document**
in the Paperless inbox UI which belongs to an active
non-staff parent, retains its inbox tag, has OCR text and is
not manually pre-reviewed. Put its existing positive integer
Paperless document ID in the private gitignored
`paperless_ai_catalog_pilot_ids` (single-element list),
set `paperless_ai_catalog_mode: preview`, leave
`paperless_ai_catalog_approved: false` and
`paperless_ai_catalog_timer_activate: false`, and re-run
`manage-paperless-ai-inbox-catalog.yml` with the private
vars file. Expected `AUDIT=READ_ONLY`,
`STATUS=READY`, `ELIGIBLE_SAMPLE=1`,
`APPLIED=0` and `CHANGED=False`.

The preview validates scope; it does not show an LLM proposal,
run inference, or make changes. No implicit approval to
set `mode: apply` follows. Any actual one-document
pilot still needs explicit, scoped document-write consent,
review of backup/rollback and the outstanding access-control
risk that the user elected to defer; do not claim that
deferred TCP/11434 exposure has been fixed.

## Pilot preview 2026-10-20 13:21 – no eligible selection and private diagnosis

The operator ran the protected `manage-paperless-ai-inbox-catalog.yml`
with the local vars file and received:

```text
AUDIT=READ_ONLY
STATUS=READY
ELIGIBLE_SAMPLE=0
APPLIED=0
REVIEW_REQUIRED=0
ALREADY_RECORDED=0
ROLLED_BACK=0
CHANGED=False
venombox ok=9 changed=0 failed=0 skipped=1
```

The previously observed `ELIGIBLE_SAMPLE=8` was a
**different earlier input state**. `STATUS=READY`
confirms the model/configuration path; `ELIGIBLE_SAMPLE=0`
means the current scoped preview chose no qualifying document.
Neither output identifies *which* condition rejected a selected
ID. Relevant upstream and local predicates: selected ID may
not exist; document owner may be absent, inactive, privileged,
or outside the exact approved Paperless Django parent group;
the real inbox tag may be absent; OCR content may have fewer
than 30 nonblank characters; or document version metadata
may exclude it. When `pilot_ids` is empty, the
`min_document_id` watermark can independently exclude
documents. Do not guess the reason or automatically expand
the allowed group.

A new, narrow **read-only eligibility audit** is available in
this branch at
`ansible/playbooks/audit-paperless-ai-pilot-selection-readonly.yml`.
It reads only the exact selected `pilot_ids` (max two)
and up to thirty parent-owned inbox candidates through the
existing Paperless Django ORM, matching the worker's
eligibility logic. It does **not** run the model, create a
journal, write document fields, or modify permission
assignments. The normal report gives a reason category
for the selected IDs, without exposing their numeric
values or any document metadata. The user explicitly
asked for alternate actual IDs; listing up to eight
matching integer IDs requires an **additional, explicit**
`paperless_ai_catalog_show_candidate_ids=true` flag
and emits IDs **only into the operator's private terminal**.
Do not commit or publish this output to GitHub, chat logs
or the repository.

From `bp-controller`, with the reviewed ignored local vars:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-pilot-selection-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e paperless_ai_catalog_show_candidate_ids=true
)
```

Interpretation:
- `PILOT_ELIGIBILITY=DOCUMENT_ABSENT`, `OWNER_INACTIVE`,
  `OWNER_PRIVILEGED`, `OWNER_OUTSIDE_PARENT_GROUP`,
  `INBOX_TAG_MISSING`, `OCR_INSUFFICIENT` or
  `VERSIONED_DOCUMENT` specifies the **first** rejection.
  `ELIGIBLE` means the exact selected ID qualifies on
  current ORM state.
- `PILOT_ELIGIBILITY=NOT_SELECTED` means that local
  `pilot_ids` is empty. An active positive watermark,
  changed data or a different local vars file may then
  explain a count of zero in the original catalogue preview.
- `ELIGIBLE_CANDIDATE_IDS=...` (opt-in) lists up to
  eight currently valid **numeric candidate IDs**.
  Choose exactly one, set the site's gitignored
  `paperless_ai_catalog_pilot_ids: [ID]`,
  keep `paperless_ai_catalog_mode: preview` and
  **all** approval/timer flags false, then re-run the
  original preview. Expected `ELIGIBLE_SAMPLE=1`.
  An eligible ID list is a private operator-only
  selection aid, not an approval for model inference.

The current read-only route/metadata checks do not
authorize a one-document AI write. The unresolved Ollama
wildcard TCP/11434 exposure and the CT126 20 Oct backup
failure remain independent, documented operational risks.


## Pilot selection diagnosis: privileged owner (2026-10-20)

The operator executed the bounded, non-writing Paperless Django
eligibility audit for a single pilot document:

```text
AUDIT=READ_ONLY
CHANGED=False
STATUS=INSPECTED
PILOT_SELECTION_COUNT=1
PILOT_ELIGIBILITY=OWNER_PRIVILEGED
ELIGIBLE_CANDIDATE_COUNT_SHOWN=8
MODEL_INFERENCE=NO
DOCUMENTS_CHANGED=NO
```

The selected pilot's owner has Paperless `is_staff` or
`is_superuser` privileges. The first-matching failure
category does **not** disclose which privilege flag is set;
the worker intentionally excludes both. This is a
document-owner authorization scope failure, not an Ollama
readiness or model connection issue. Do **not** strip
administrative rights, transfer ownership automatically,
broaden the approved parent group, or bypass the policy to
force the initial pilot.

The query also verified **eight alternative candidate IDs**
within the bounded, parent-owned, OCR-complete inbox scope.
The operator's excerpt did not include the optional actual
numeric ID list: if requested, the final debug task displays
`ELIGIBLE_CANDIDATE_IDS` locally. Choose exactly one of
those alternatives in the Paperless UI and the ignored
`paperless_ai_catalog_pilot_ids: [ID]`, leave
`paperless_ai_catalog_mode: preview` and all
approval/timer flags false, then repeat the original
read-only preview. Expected `ELIGIBLE_SAMPLE=1` is
necessary before separately approving a one-document
metadata write. No inference has run.


## Live 2026-10-20 – eligible one-document pilot selected

Operator re-ran the narrowly scoped read-only eligibility diagnostic
on the one document selected in the private local site variables:

```text
AUDIT=READ_ONLY
CHANGED=False
STATUS=INSPECTED
PILOT_SELECTION_COUNT=1
PILOT_ELIGIBILITY=ELIGIBLE
ELIGIBLE_CANDIDATE_COUNT_SHOWN=8
MODEL_INFERENCE=NO
DOCUMENTS_CHANGED=NO
```

The operator additionally received exactly eight numeric alternative
candidate IDs on the private `bp-controller` terminal. IDs and
document metadata are intentionally **not recorded in Git**.
The selected owner now satisfies the non-staff/non-superuser parent
scope, inbox-tag, OCR-length and no-version eligibility predicates.
This only proves present **eligibility**, not permission to write,
a successful native classification or presence of applicable metadata
suggestions.

Next, with the exact approved candidate ID retained in the ignored
local variables file, run `manage-paperless-ai-inbox-catalog.yml`
in explicit `paperless_ai_catalog_mode=preview`. Require
`STATUS=READY`, `ELIGIBLE_SAMPLE=1`,
`APPLIED=0`, `CHANGED=False`.
Do not start a pilot `apply` on this diagnosis alone:
a separate document-scoped operator approval and review of
rollback/integrity evidence remain necessary. Keep global AI,
embeddings, timer and network/firewall changes disabled.

## Live one-document catalog preview READY (20.10.2026)

After the separate private pilot selection audit showed `PILOT_ELIGIBILITY=ELIGIBLE`, the operator executed the **actual**
`manage-paperless-ai-inbox-catalog.yml` in read-only preview mode for
exactly one reviewed Paperless inbox document. Observed output:

```text
AUDIT=READ_ONLY
STATUS=READY
PAPERLESS_VERSION=3.3.0
ELIGIBLE_SAMPLE=1
APPLIED=0
REVIEW_REQUIRED=0
ALREADY_RECORDED=0
ROLLED_BACK=0
CHANGED=False
```

The existing Paperless 3.3.0 Ollama configuration, the selected
Qwen model and the document scope all passed. **No LLM
classification was invoked and no metadata was changed.**
The selected numeric document ID and its content are not
stored in Git.

**Remaining deliberate operator gate:** Explicit approval
to run one production AI classification that may alter the
selected document's title, correspondent, type and additive
existing tags, writing a protected processing journal.
The manually accepted 19 Oct CT126 archive passed
Zstd/TAR structure checks but was not full-restore tested;
the scheduled 20 Oct backup failed (rc 255).
The Ollama unauthenticated wildcard IPv4/IPv6 access
remains a separate acknowledged, unresolved risk.

Once the owner explicitly approves a **single** document
metadata pilot, use the pre-existing `manage-paperless-ai-inbox-catalog.yml`
with the reviewed **unchanged single** `paperless_ai_catalog_pilot_ids`,
batch size one and per-invocation extra vars:
`paperless_ai_catalog_mode=apply`,
`paperless_ai_catalog_approved=true`,
`paperless_ai_catalog_verified_backup=true`
(the latter only under the operator's explicit acceptance
of the pinned backup for this distinct document-write
change). Never enable a timer or process the eight candidates
as a batch. Afterward inspect the real Paperless UI and
journal category before contemplating a separately gated
rollback or automatic processing.

## Operator scope expansion: all currently eligible inbox documents (2026-10-20)

Following the successful one-document read-only `ELIGIBLE_SAMPLE=1`
preview, the operator explicitly approved **all eight**
currently eligible parent-owned inbox candidates for local
Paperless native Qwen classification. This supersedes the
previously contemplated **one-document-only** pilot
authorization for this one manual execution session;
it is **not** an ongoing, scheduled, or future-document
authorization. Preserve the reviewed set of eight exact
numeric IDs in the operator's private local workflow only
(do **not** write them to Git).

Implementation constraints from the existing, unmodified
`bergen_ai_catalog_runner.py`:
- `MAX_BATCH=2`; use **one exact pilot ID per invocation**
  with `batch_size=1` to fail-stop between documents.
- Require operator-accepted 19 October CT126 `vzdump`
  as the rollback reference; Zstd stream and TAR structure
  passed but **no full-restore evidence** exists.
- Per one-document apply, set only oneoff non-persistent
  overrides: `paperless_ai_catalog_pilot_ids: [ID]`,
  `paperless_ai_catalog_mode: apply`,
  `paperless_ai_catalog_approved: true`,
  `paperless_ai_catalog_verified_backup: true`,
  `paperless_ai_catalog_batch_size: 1`.
- Retain `paperless_ai_catalog_timer_activate=false` and
  all permanent site-local write approvals false.
- After each exit status 0, require exact
  `STATUS=COMPLETED`, `APPLIED=1`,
  `REVIEW_REQUIRED=0`, `ALREADY_RECORDED=0`
  and `CHANGED=True`. Stop immediately on any mismatch
  or nonzero Ansible status; do not infer a failed Ansible
  run had no partial effect, as a document may remain
  in the protected `REQUIRES_REVIEW` journal.
- ORM `eligible()`, document optimistic snapshot
  checks and journal idempotency are re-evaluated on
  **each** apply; pilot IDs do not bypass owner,
  staff/superuser, inbox, OCR, or version safeguards.
- No automatic rollback on a failed step. Journal and
  the actual document must be reviewed first, and
  rollback is a separately gated action.
- The selected Qwen LLM has no permissions beyond the
  existing Paperless process identity by this apply.
  The unauthenticated Ollama port exposure and the
  20 October daily backup failure remain open incidents.

The human has authorized the **scope**, but no one can
claim that production documents were updated until
`bp-controller` runs the per-ID commands and returns
their actual `APPLIED` counts. The workflow must not
silently process new inbox arrivals or all documents
without the pinned candidate set.

## One-document-per-run bulk trial STOP at document 11 – 2026-10-20 15:28

The operator executed the eight-ID manually approved one-document-at-a-time
classification loop and provided the following output excerpt:

```text
DOC 2:  previous per-ID step confirmed as successful by 3/8 counter
DOC 5:  previous per-ID step confirmed as successful by 3/8 counter
DOC 10: AUDIT=CONTROLLED STATUS=COMPLETED
        APPLIED=1 REVIEW_REQUIRED=0 ALREADY_RECORDED=0 CHANGED=True
        changed=1 failed=0
CONFIRMED=3/8

DOC 11: "Report only a reviewed, non-identifying error classification" SKIPPED
        "Fail closed if runtime rejected a configuration or write attempt" FAILED
        CATALOG_AUDIT_FAILED_OR_REQUIRES_REVIEW
        changed=0 failed=1 (Ansible report)
STOP: Ansible-Fehler bei DOC 11
```

**Operationally:** The shell loop stopped as designed; documents
16, 21, 22, 29 have **not been attempted** in that execution.
Ansible `changed=0` at the failure step does **not** prove
the document metadata was unchanged: the worker catches the
exception, persists `REQUIRES_REVIEW` in the private processing
journal, then reports an outcome that the guarded Ansible assert
rejects. The skipped error classification implies the underlying
`pct exec` command exited with code zero, making an ordinary
`REVIEW_REQUIRED=1` outcome a strong but not yet independently
verified hypothesis. It is **not evidence** of a failed network
connection or failed classification step in particular: the worker
intentionally suppresses exception details and cannot reconstruct
them after the fact.

**No automatic retry and no rollback** of document 11, and no
further batch processing pending a forensic read-only comparison
between the persistent journal pre-image and current Django ORM
snapshot. A diagnostic with bounded, non-identifying categories
has been committed:

- `ansible/files/paperless/audit_ai_catalog_review_state_readonly.py`
- `ansible/playbooks/audit-paperless-ai-catalog-review-readonly.yml`

This audit reads exactly the selected document ID and its
`catalog.sqlite3` row using SQLite `mode=ro` and
`PRAGMA query_only=ON`; it never performs OCR/LLM inference,
reads/logs document text, changes the journal, or changes
Paperless metadata. Its output reveals `JOURNAL_STATE`,
`SNAPSHOT_MATCH` (`MATCH` or `DIFF`),
`DIFFERENCE_CATEGORY`, the presence of the inbox tag
and whether an after-snapshot was recorded. A matching
snapshot means no **currently observable** changes to
the guarded ORM fields compared to the pre-inference
journal pre-image; it is not proof that no transient
write ever happened or that nobody else changed the
document meanwhile.

Run from `bp-controller` after a GitHub branch fetch,
with local private site var file and an explicit document
selection:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-catalog-review-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e paperless_ai_catalog_review_document_id=11
)
```

If `JOURNAL_STATE=REQUIRES_REVIEW` and
`SNAPSHOT_MATCH=MATCH`, the document has not
observably changed since the durable pre-image, but
the journal blocks automatic retry. Any explicit
one-record journal reset/retry requires a distinct
policy and review authorization; **never remove
the journal row or manipulate SQLite manually**.
If `SNAPSHOT_MATCH=DIFF`, inspect the live Paperless
document UI and reconcile the pre-image with any
concurrent user work before authorizing any rollback.

The accepted 19 October CT126 backup is unchanged;
20 October daily backup rc 255 and wildcard Ollama
TCP/11434 access remain open issues. All eight documents
have not been classified successfully.


## Live document 11 journal audit – baseline preserved (2026-10-20 15:38)

Operator executed `audit-paperless-ai-catalog-review-readonly.yml`
with exact `paperless_ai_catalog_review_document_id=11`.
The existing Proxmox Paperless guest was verified, and all
Ansible tasks passed without changes:

```text
AUDIT=READ_ONLY
STATUS=INSPECTED
JOURNAL_STATE=REQUIRES_REVIEW
SNAPSHOT_MATCH=MATCH
DIFFERENCE_CATEGORY=NONE
INBOX_TAG=PRESENT
JOURNAL_AFTER_SNAPSHOT=ABSENT
MODEL_INFERENCE=NO
DOCUMENTS_CHANGED=NO
CHANGED=False
venombox ok=9 changed=0 failed=0
```

**Conclusions:** The persistent journal has marked document
11 for manual review and therefore prevents an unreviewed
retry. At read time the document's protected owner/title,
source fingerprint, OCR hash, type, correspondent, tag set,
inbox state and timestamps matched the journal preimage.
No completed after-snapshot exists. This does **not** reveal
the original Python exception, establish whether the earlier
attempt invoked inference, or prove no transient writes
occurred; `MODEL_INFERENCE=NO` applies **only to this
subsequent audit**. Do not remove, alter or purge its SQLite
journal entry and do not run a second `apply` for document
11. Its current user-facing metadata remains as before.

The operator had already explicitly authorized the fixed
eight eligible document candidates. The documented,
one-document-per-invocation fail-stop processing can
resume **only for the four not-yet-attempted candidate
IDs**, never include previously recorded documents
2, 5, 10 or blocked document 11 in the resumption.
Pre-existing eligibility and configuration gates must
run on each invocation; require `APPLIED=1`,
`REVIEW_REQUIRED=0`, `ALREADY_RECORDED=0`,
`CHANGED=True` after each, and stop on any anomaly.
Do not equate the approval with automation, timer
activation or future unbounded scans.

After the four outstanding IDs have been attempted,
inspect outcomes before any decision on a separate,
version-pinned explanation and repair workflow for
document 11. The routine cannot retrospectively
recover the exception because the runner intentionally
does not emit or retain it. Backup job rc 255 and
Ollama port exposure remain independent open issues.

## Controlled continuation stopped on existing journal record at document 16 (2026-10-20 15:44)

After the approved 8-document run stopped at document 11,
the read-only journal audit showed document 11
`REQUIRES_REVIEW` with `SNAPSHOT_MATCH=MATCH`
and `INBOX_TAG=PRESENT`. The operator then resumed the
four remaining candidates (16, 21, 22, 29) with
one-document-per-apply fail-stop logic. The **first** step,
document 16, returned:

```text
AUDIT=CONTROLLED
STATUS=COMPLETED
PAPERLESS_VERSION=3.3.0
ELIGIBLE_SAMPLE=N/A
APPLIED=0
REVIEW_REQUIRED=0
ALREADY_RECORDED=1
ROLLED_BACK=0
CHANGED=False
venombox ok=9 changed=0 failed=0
STOP: DOC 16, Ergebnis nicht bestätigt
```

The loop intentionally stopped; documents 21, 22, 29
were not processed **in this continuation**. The worker's
`process_one` returns `ALREADY_RECORDED` if *any*
persistent `catalogue` journal row exists for the ID,
independently of its state. Therefore the status
`COMPLETED` is only the outcome of this **no-op**
command: it does **not** prove that document 16 was
classified successfully in a previous run, and does not
disclose whether its existing journal state is
`APPLIED`, `REQUIRES_REVIEW`, `PROCESSING` or
`ROLLED_BACK`. The earlier claim that document 16 was
never previously attempted cannot be established by
the observed partial shell output.

**Next gate, no writes:** inspect document 16 with
the already tested
`audit-paperless-ai-catalog-review-readonly.yml`
(`paperless_ai_catalog_review_document_id=16`),
which compares the journal's preimage with live
Django metadata, classifies its actual persistent
state and verifies the inbox tag. Do not delete or
edit the SQLite journal, rerun document 16 blindly,
or continue the batch before reviewing that result.
All documents with `APPLIED=1` remain unchanged by
these audits.

The unresolved scheduled CT126 backup rc 255 and
Ollama wildcard-port exposure remain separate issues.

## Second review-required document confirmed – 2026-10-20 15:47

Operator investigated document 16 with the existing
`audit-paperless-ai-catalog-review-readonly.yml`:

```text
AUDIT=READ_ONLY
STATUS=INSPECTED
JOURNAL_STATE=REQUIRES_REVIEW
SNAPSHOT_MATCH=MATCH
DIFFERENCE_CATEGORY=NONE
INBOX_TAG=PRESENT
JOURNAL_AFTER_SNAPSHOT=ABSENT
MODEL_INFERENCE=NO
DOCUMENTS_CHANGED=NO
CHANGED=False
venombox ok=9 changed=0 failed=0
```

Documents 11 and 16 are both durable `REQUIRES_REVIEW`
entries and their current protected metadata match their
respective saved pre-inference journal snapshots. This
does *not* establish a specific underlying classifier
failure; no live OCR, AI prompt, model response or
exception message is retained by these redacted
audits. A second independent `REQUIRES_REVIEW` case
warrants treating the bulk workflow as **paused**, not
as authorization to bypass the one-document fail-stop.

Known results from the authorized eight-ID set:
- 2, 5, 10: `APPLIED=1` in prior individual executions
  (verified previously via `CONFIRMED=3/8`).
- 11, 16: `REQUIRES_REVIEW`, matching baseline, inbox
  still tagged.
- 21, 22, 29: not executed in the two observed loops;
  earlier journal presence is **not yet established**.

### Next non-mutating action: inventory exactly the eight pinned IDs

A purpose-built read-only playbook at
`ansible/playbooks/audit-paperless-ai-catalog-journal-inventory-readonly.yml`
takes a **caller-provided** positive-integer ID list, max
eight, and reads only those statuses through the existing
Paperless Django runtime and `sqlite3 mode=ro` with
`PRAGMA query_only=ON`. Output contains only exact
operator-specified numeric IDs and status enums
`APPLIED`, `REQUIRES_REVIEW`, `PROCESSING`,
`ROLLED_BACK`, `NOT_RECORDED`. No OCR/metadata is
queried or logged, no inference is run, and no journal
or document changes are authorized.

From `bp-controller` using the ignored local site
variables, after updating the detached worktree:

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-catalog-journal-inventory-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{"paperless_ai_catalog_journal_document_ids":[2,5,10,11,16,21,22,29]}'
)
```

This inventories previous journal states without requesting
another classification of previously attempted documents.
Even if IDs 21/22/29 are `NOT_RECORDED`, any additional
writes remain separately considered after diagnosing the
repeated review outcomes. Do not manually delete any
`catalog.sqlite3` row or reset the journal. Open
CT126 daily backup failure and unauthenticated Ollama
TCP/11434 surface remain separate unresolved findings.


## Authoritative eight-ID journal inventory 2026-10-20 15:55

Operator ran the newly introduced read-only, bounded journal
inventory against exactly the eight IDs from the pre-approved
Paperless AI candidate set. All nine tasks passed,
`changed=0`, and no model inference occurred:

```text
AUDIT=READ_ONLY
STATUS=INSPECTED
SCOPED_COUNT=8
ID_AND_STATE=[
  {"document_id":2,"state":"APPLIED"},
  {"document_id":5,"state":"APPLIED"},
  {"document_id":10,"state":"APPLIED"},
  {"document_id":11,"state":"REQUIRES_REVIEW"},
  {"document_id":16,"state":"REQUIRES_REVIEW"},
  {"document_id":21,"state":"NOT_RECORDED"},
  {"document_id":22,"state":"NOT_RECORDED"},
  {"document_id":29,"state":"NOT_RECORDED"}
]
MODEL_INFERENCE=NO
DOCUMENTS_CHANGED=NO
CHANGED=False
venombox ok=9 changed=0 failed=0
```

This establishes the durable journal status, not the
subjective *quality* of the three successfully applied
AI classifications. Review actual Paperless metadata in
the UI; manual inbox-tag removal remains exclusively
the operator's decision. Documents 11 and 16 remain
blocked pending documented, separately gated recovery;
their preimage audits show `MATCH` and inbox tag present.
The journal did not retain the original Python exception,
so the root cause cannot be asserted from these results.

The remaining IDs 21,22,29 have **no existing journal
entries**, so they can be handled only as separate
one-document, user-approved operations with the same
policy, backup acknowledgement and fail-stop assertions.
Never include 11 or 16, retry their journal entries,
wipe any journal row, or activate the timer implicitly.
Given two failures among five prior attempts, treat further
`REQUIRES_REVIEW` as a meaningful recurring incident:
stop again immediately on the first non-success;
do not claim remaining files were attempted.
Alternatively, pause all mutations to first investigate
the classifier's error modes. Both choices preserve the
original explicit fixed-eight scope.


## Hypothesis after operator manually edited an AI-classified document – 2026-10-20

The operator reports a **temporal correlation**:
multiple `REQUIRES_REVIEW` outcomes occurred after
a human manually edited one document already classified
by Bergen's native Paperless/Ollama worker. The exact
manually edited document and which metadata fields
were changed have **not** been established. Do not
state causality as proven.

Two code paths deserve separate review:

1. The native Paperless AI classifier may select
   context/taxonomy candidates from similar documents
   (Paperless v3.2+ introduced a Tantivy full-text
   fallback when embeddings are off). A human edit can
   change the source metadata or text considered by
   subsequent similarity/taxonomy suggestions. However
   the local Qwen model is **not fine-tuned or retrained**
   by metadata edits; native Paperless's suggestion
   context and deterministic Paperless classifier model
   are different mechanisms.
2. Our pinned `bergen_ai_catalog_runner.py`
   **conflates a valid no-op with operational errors**:
   `plan_changes` deliberately preserves manually
   edited titles, does not override nonempty
   correspondent/document type, creates no missing tags,
   and appends only existing valid tags.
   `process_one` raises
   `PolicyError("NO_APPLICABLE_SUGGESTIONS")`
   if all four change groups are empty. The blanket
   `except Exception` catches this alongside
   network/schema/LLM failures, marks a durable
   `REQUIRES_REVIEW` row, and does **not** persist
   a sanitized cause. The Ansible gate then correctly
   aborts further processing. This is an actionable
   semantic/observability design issue irrespective of
   whether it caused any one earlier failure.

The operator's later journal inventory had documented
three `APPLIED`, two `REQUIRES_REVIEW`,
three `NOT_RECORDED`; **subsequent** operator output
confirmed additional `REQUIRES_REVIEW`-style failures
for 21 and 22 but their newest journal states have
not been independently re-inventoried. Do not assert
all previously blocked documents now have proven
identical live snapshots; only 11 and 16 had individual
`SNAPSHOT_MATCH=MATCH` proofs.

**Operational decision:** Pause all further AI
document writes including ID 29; do not clear the
existing `REQUIRES_REVIEW` SQLite entries.
Do not alter Ollama, global AI configuration, owner
roles, tags or the Paperless document versions
while analyzing the correlation.

**Required engineering change before further production
pilots:** introduce explicit, safe, bounded phases
(`LLM_CALL`, `RESOLVE_CHOICES`, `PLAN_CHANGES`,
`OPTIMISTIC_SNAPSHOT`, `DB_UPDATE`,
`JOURNAL_COMMIT`) and stable allowlisted error categories
captured without OCR/document text/LLM prompts/raw
exception messages. Treat a *validated, successful*
classification whose planned metadata diff is empty
as a separately reviewed `NO_CHANGE` terminal status,
not as `REQUIRES_REVIEW`; retain protected journal and
idempotency. Maintain a distinct review-required outcome
for an indeterminate or partially committed write.
No automatic replay of failed IDs, journal reset,
simulated error cause, or new inference is authorized
by this documentation.


## Operator clarified post-AI changes to document 10: NEW document type and tag

Operator clarified that after Qwen successfully classified
Document **10**, they **created** a new Paperless document type
named `Zertifikat` and a new tag (name not supplied),
then assigned those newly created taxonomy objects to
Document 10. These are newly created *matching objects*,
not merely a choice between pre-existing categories.

This change cannot retrain the installed Ollama Qwen weights,
but can influence Paperless-ngx 3.3 retrieval-assisted AI
classification: its classification flow derives eligible
tag/type candidates from visible similar documents, even
when embeddings are disabled (Tantivy full-text fallback).

Importantly, in Paperless tags and document types are
separate owner-/object-permission-protected objects.
Bergen's native v3.3 catalogue runner invokes the
classifier as the **target document owner** and uses
permission-aware `resolve_*_ids` / `match_*_by_name`
and `create_missing=False`; newly created private
taxonomy objects may be visible on manually edited
Document 10 but not matchable by other owners. This is
a live-testable hypothesis, **not** proof that it caused
the subsequent LLM or no-op failures. No raw AI response
or sanitized error stage was retained by the old worker.

To verify the precise category visibility safely, this
branch adds the read-only scoped
`audit-paperless-ai-taxonomy-visibility-readonly.yml`.
It compares Document 10's protected journal *post-AI*
`after_json` with its current type/tag IDs, then uses
Paperless's own `permitted_object_ids` for document owners
11, 16, 21, 22, 29. It only displays operator-known
document IDs, owner-equality classification, yes/no
document-type view permission and count of the
post-AI-added tags visible to each owner. It also
reports whether the current Doc 10 type really equals
`Zertifikat`; it never emits the new tag name, real
tag IDs, owner IDs, title, OCR or journal JSON, never
performs inference and does not change metadata or
Paperless permissions.

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
test -z "$(git -C "$WT" status --porcelain)" || {
  echo "STOP: uncommitted worktree changes"; exit 1;
}
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-taxonomy-visibility-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

Interpretation: `POST_AI_TYPE_CHANGED=True` and a
positive `POST_AI_TAGS_ADDED_COUNT` confirm the
post-AI manual changes relative to a prior saved
journal state. `TYPE_VISIBLE=NO` or only partial
`ADDED_TAGS_VISIBLE` among the failing targets
supports a taxonomy ACL mismatch that needs
further causal investigation. If all categories are
visible to all owners, prioritize the current worker
`NO_APPLICABLE_SUGGESTIONS` semantic flaw and
unclassified LLM/matching exceptions. Do not
automatically alter permissions: a private type/tag
may be intentionally restricted.

**Outstanding:** Document 29 is unattempted, and
11/16/21/22 are under review by operator report.
Do not start new classification, reset journal rows,
or change the classification code in production
until separate validation/release. The scheduled
20 October CT126 backup failure and Ollama
network exposure remain independent work items.
