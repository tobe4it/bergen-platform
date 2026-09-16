# IBM MQ declarative administration

> This implementation is an **example / evaluation only**, not approved for
> productive operation. Before productive use, clarify the license question
> with IBM. **Für den produktiven Betrieb ist die Lizenzfrage mit IBM zu klären.**

For an Ansible-provisioned Rocky LXC + Podman test target, see [MQ lab](MQ-LAB.md).

## Status and feasibility (2026-09-15)

The proposal in IBM Idea [MESNS-I-1050](https://ideas.ibm.com/ideas/MESNS-I-1050)
asks for an officially supported, cross-platform Ansible collection with full
MQ object/security coverage. This repository implements a **bounded,
project-maintained prototype**, not that complete product or IBM support.

IBM already publishes [ibm_messaging.ibmmq](https://github.com/ibm-messaging/mq-ansible)
for installation/configuration. Its README explicitly excludes commercial IBM
support and warranty. IBM's [YAML commands samples](https://github.com/ibm-messaging/mq-ansible-yaml-commands)
demonstrate structured MQSC over the administrative REST API. They are command
execution examples, not evidence that all proposal acceptance criteria are met.

The Bergen module uses [JSON-formatted MQSC](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=adminactionqmgrqmgrnamemqsc-post-json-formatted-command)
over authenticated HTTPS. It queries actual state, compares only declared
attributes, sends DEFINE or incremental ALTER only when needed, and verifies
each mutation with another DISPLAY. Unspecified attributes remain unmanaged.
Objects omitted from YAML are **never pruned**.

| Requirement | Implementation/status |
| --- | --- |
| `present`, real desired-state comparison | Implemented for the bounded object/attribute set below |
| `absent` | Explicit deletion gate, exact names, no FORCE/PURGE |
| `--check --diff` | DISPLAY-only requests and structured before/after projections |
| Central remote administration without SSH | Controller-local HTTPS mqweb connection |
| CHLAUTH and OAM | Not implemented; security record identities/authority sets require dedicated reconciliation |
| Subscriptions, QMGR, services, cluster lifecycle | Not implemented |
| Local bindings or PCF client transport | Not implemented |
| Official IBM support / complete cross-platform coverage | Cannot be provided by this project |
| Real MQ acceptance / rollout | Pending a reachable, authorized MQ test environment |

The initial target is an existing MQ 9.4 queue manager exposed through mqweb.
REST v2/v3 URL forms are accepted, but that is not a compatibility certification
for MQ 9.3, z/OS, AIX, IBM i, Windows or the MQ Appliance. Validate each intended
MQ version/platform separately. No MQ package, license acceptance, LXC or new
queue manager is provisioned by the reconciler itself. The separate MQ lab
workflow prepares an evaluation target only. MQTT remains the home-platform
message broker; this is MQ **administration**, not a daytrading event bridge.

## Object and attribute boundary

Use lower-case declaration types/attribute names. Enum values are normalized
case-insensitively; object names, descriptions, topic strings, connection names
and namelist entries retain case. Quote YAML `"yes"`/`"no"`; integers must be
actual YAML integers, not strings or booleans. Unrecognized fields/attributes
fail before any network request.

All types accept `descr`. Additional supported attributes:

| Type | Attributes |
| --- | --- |
| `qlocal` | `maxdepth`, `maxmsgl`, `defpsist`, `put`, `get`, `usage` |
| `qremote` | `rname`, `rqmname`, `xmitq`, `defpsist`, `put` |
| `qalias` | `target`, `targtype`, `defpsist`, `put`, `get` |
| `qmodel` | `maxdepth`, `maxmsgl`, `defpsist`, `deftype`, `put`, `get` |
| `channel` | `chltype`, `conname`, `xmitq`, `maxmsgl`, `hbint`, `kaint`, `discint`, `sslciph`, `sslcauth` |
| `topic` | `topicstr`, `pub`, `sub`, `pubscope`, `subscope`, `defpsist` |
| `namelist` | `names` (ordered list), `nltype` (z/OS only; omit on Linux) |

Present channels require `chltype`: `sdr`, `rcvr`, `svrconn`, `clntconn`,
`clussdr` or `clusrcvr`. Creating SDR/CLNTCONN/CLUSSDR also requires `conname`.
Creating SDR additionally requires `xmitq`; an existing SDR can still be managed incrementally.
Creating a topic requires `topicstr`. Channel/queue type changes and changing an
existing topic's `topicstr` are refused; no automatic replacement is attempted.
Integer attributes are restricted to non-negative integers (e.g. KAINT AUTO
is not supported in this prototype). For enum values see `ENUM_VALUES` in
`ansible/module_utils/bergen_mq.py`; this is intentionally not arbitrary MQSC.

Queue discovery uses DISPLAY QUEUE with all attributes so a conflicting queue
type is detected. The JSON MQSC response uses `type: QLOCAL`, not the `local`
value used by a different REST queue resource. Only a detail failure
`completionCode=2`, `reasonCode=2085` (unknown object), with no successful
object rows and an accepted overall envelope, is treated as absence. IBM's
[REST MQSC examples](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=adminactionqmgrqmgrnamemqsc-post-plain-text-mqsc-command)
show the overall command-failed reason `3008` wrapping that detail. HTTP 404,
authorization errors, warnings, malformed responses and unfamiliar codes fail
closed, not as "missing".

## Prerequisites

- Authorized, existing test queue manager and running mqweb administrative API
- Direct controller-to-mqweb HTTPS access; environment proxies are not used
- Valid hostname certificate and trusted CA; optional `mq_rest_ca_path` points
  to a CA bundle **on the controller**. TLS verification cannot be disabled.
- Dedicated REST identity with the appropriate mqweb role and MQ authorities
  for DISPLAY and the explicitly approved DEFINE/ALTER/DELETE operations
- Credentials in Ansible Vault, not Git or command-line arguments
- Python 3 and ansible-core on the controller; no additional runtime MQ client

Do not grant shared `mqm` administrator access as a convenience default. Existing
CHLAUTH, CONNAUTH, OAM/RACF and TLS policy must be reviewed separately. The
module does not weaken, create or certify those policies. The approved MQ
administrator must set up the required API access through the site's existing
process before a rollout.

## Controller workflow

From the repository root on bp-controller:

```bash
cp ansible/vars/mq.example.yml ansible/vars/mq.local.yml
vim ansible/vars/mq.local.yml
ansible-vault edit ansible/group_vars/all/vault.yml
```

Add `vault_mq_rest_password` to the encrypted Vault file. Fill endpoint, QMGR,
identity, CA and intended objects in the ignored local file. Do not use example
objects against production until reviewed. Existing repository `ansible.cfg`
loads the custom module and its module_utils; run from the repository root.

Preview against the real test queue manager:

```bash
ansible-playbook ansible/playbooks/mq-objects.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq.local.yml --ask-vault-pass --check --diff
```

After reviewing the diff, repeat without `--check` to apply. Run again afterward;
the unchanged declaration must report `changed=false`. The module performs
complete declaration validation and discovery before its first mutation.
Independent objects are applied **in declared order**, not dependency-sorted;
declare referenced objects first. `--check` uses POST requests containing only
DISPLAY commands (a POST is not automatically a write operation).

For an approved deletion, explicitly declare `state: absent` without attributes
and set `mq_allow_deletion: true`. Removing an entry from YAML never deletes it.
IBM [DELETE queues](https://www.ibm.com/docs/en/ibm-mq/9.3.x?topic=reference-delete-queues)
defaults to NOPURGE, so non-empty local queues are not forcibly deleted. This
is not a substitute for a backup or a deletion approval; deletion may also
affect associated authority records. Keep deletion enabled only for the
specific reviewed run.

## Governance and failure handling

Use Git/PR review, separately enforced approval and a serialized pipeline per
QMGR. The module supplies state comparison, not branch protection, approval
enforcement or an immutable audit store. Preserve pipeline commit, approver,
diff, runtime and verification evidence under site policy. Connection secrets
are `no_log` module parameters; HTTP error bodies are never included in output.
Diffs contain configuration values, which may themselves require protected
pipeline logs. Credential redirects and unverified TLS are refused.

MQ commands across objects are **not transactional**. Concurrent administration
can race between DISPLAY and ALTER; the module does not provide a distributed
lock. On a failed mutation, successful prior commands are reported as `applied`
and `mutation_outcome_requires_review=true` flags possible partial/unknown
state. Network timeouts can occur after MQ accepted a command. There are no
automatic mutation retries or blind rollback/deletion. Inspect actual state
with a new check run and follow the site's incident/change procedure.

## Tests and remaining acceptance

```bash
python3 -m unittest discover -s tests -v
ansible-playbook ansible/playbooks/mq-objects.yml -i localhost, --syntax-check
# On a controller allowing Ansible local RPC/IPC, also run full runtime tests:
BERGEN_MQ_RUN_ANSIBLE_INTEGRATION=1 python3 -m unittest discover -s tests -v
```

Unit tests exercise reconciliation and safeguards. HTTPS transport tests use a
**local mock**, including trusted/untrusted certificates, redirects,
authentication errors, check mode, apply and second-run idempotence. Opt-in
tests additionally exercise real Ansible packaging/execution and output secret
redaction. Test dependencies are ansible-core and cryptography.

Here, unit and direct HTTPS transport tests can run, and Ansible syntax/module
documentation checks succeed. Full Ansible execution is **not verified**: the
development environment denies the local RPC socket (PermissionError), before
any module execution. The five full-runtime tests are opt-in and otherwise
reported as skipped, not successful. Run them on bp-controller before acceptance.
None of these mock tests prove actual IBM MQ semantics.

Recorded development result for v0.9.1: **50 offline tests passed, 5 opt-in
Ansible runtime tests skipped**, including lab/inventory contracts; inventory
writer syntax checked. Earlier MQ-only validation also checked module docs
and Python compilation.

User-run real-MQ evaluation on `BERGENLAB` verified a missing local queue check
with zero mutations, creation/post-state verification of `BERGEN.LAB.SMOKE`
and an idempotent second apply with `changed=0`/zero mutations. This proves
that bounded local-queue workflow only, not all supported object types,
ALTER/deletion safeguards or the IBM Idea's full acceptance criteria.

Before production acceptance, run the reviewed declarations on a disposable,
authorized MQ 9.4 test QMGR: missing object check, create, second run, one-field
ALTER, no-drift run, type conflict, denied identity, protected non-empty queue
deletion, authorized empty queue deletion and post-state verification. Validate
each supported object type and required platform/version, retain sanitized
actual response fixtures, and test real CHLAUTH/OAM administration separately
when those reconcilers are added. Do not mark the IBM Idea's full acceptance
criteria complete from this prototype.
