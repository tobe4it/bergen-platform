# Two-QMgr / client test expansion

Evaluation only. This is an executable **partial** extension, not a claim that
every feasible MQ test is implemented. No new live MQ tests were run during
development. The earlier 158-PASS single-QMgr evidence remains separate.

## Executable coverage

| Area | Checks | Prerequisites |
| --- | --- | --- |
| Objects on A and B | Existing lifecycle/idempotency/negative/cleanup suite on each QMgr | Verified HTTPS REST administration |
| Client security | Positive TLS 1.3+peer+password connection, invalid password (2035), explicit certificate trust rejection, positive reconnection | Dedicated TLS 1.3 SVRCONN, non-admin account |
| Message content | Persistent/nonpersistent, zero bytes, binary 4 KiB, MsgId, CorrelId | Isolated BGT.* queues and scoped OAM |
| Queue behavior | Alias, browse without removal, FIFO at equal priority, priority ordering, expiry | BGT.* fixtures |
| Transactions | PUT commit/backout, uncommitted invisibility to a second connection, disconnect rollback, GET commit/backout and BackoutCount | Same-QMgr local units of work; not XA |
| Negative MQI | Empty 2033, PUT inhibited 2051, GET inhibited 2016, depth limit 2053, oversize 2030 | Generated dedicated queues |
| Authorization | Existing denied queue PUT must fail with 2035, not unknown-object/network failure | Explicit BGT.DENIED* fixture |
| A → B and B → A | Persistent, nonpersistent, 4 KiB, remote PUT commit and rollback | Existing dedicated TLS SDR/RCVR and XMITQ per direction |

Each transport GET checks bytes, MsgId and persistence on the destination. PUT
success alone is not delivery evidence. Two independent QMgr do not provide HA
for a single identity. A second connection within the same client is not a
multi-client load test. Stored persistence flags are not proof of crash survival.

## Explicitly still open

The report always lists NOT_TESTED for: mutual/client-certificate authentication,
negative CHLAUTH rules, channel interruption/backlog recovery, QMgr restart and
crash recovery, backup/restore, DLQ handler, durable/retained pubsub, cluster,
CCDT/reconnect, XA, load/soak/concurrency, message groups/segmentation/properties,
cross-QMgr request/reply correlation, certificate rotation/revocation, monitoring
delivery and upgrade/downgrade. These need further implementation and/or specific
fixtures and operating-window authorization. This release therefore cannot
produce a complete-scope PASS; a clean implemented subset yields **PARTIAL**.

## Mandatory setup before live execution

The deployment so far supplied the QMgr and Java runtime, **not** these messaging
security/transport fixtures. This test playbook deliberately does not disable
CHLAUTH, grant administrator access, change CONNAUTH, alter a QMGR-wide DLQ,
start/stop services, or automatically open firewall ports.

Prepare and review on **both** QMgr:

1. Dedicated `BGT.CLIENT` SVRCONN with TLS 1.3, configured peer identity, and a
   non-administrator principal authenticated through MQCSP. The probe requires
   `TLSv1.3` and a `TLS_AES_*` cipher suite; TLS 1.2 is deliberately rejected.
   Server authentication is covered; mutual TLS is not implemented.
2. Minimum QMGR CONNECT and test-object permissions: PUT/GET/BROWSE as needed
   only on `BGT.**`; no MQM/admin/all-object authority. The wildcard authorization
   is scoped to the reserved audit namespace, not business objects. REST admin
   creates/deletes those fixtures; the client must not administer them.
3. If OAM denial is to be tested, an existing **empty** `BGT.DENIED*` queue outside
   the effective allowed permissions (ensure the more-specific rule actually
   denies this principal). A mistakenly authorized negative PUT leaves evidence
   on that fixture; review it manually. No automatic drain is performed.
4. Two dedicated, already configured/running TLS sender/receiver pairs and
   XMITQs named `BGT.*`. Sender and receiver name must match in each direction.
   No existing application channel is stopped, started, altered or deleted.
5. Source-specific TCP 1414 access client → A/B and A ↔ B in relevant firewalls.
   Controller → A/B HTTPS remains required. With all guests on vmbr2 this does
   not test Intern → IoT routing.

Public messaging CA certificates must match the actual channel certificates.
The example reuses the lab CA paths only if those CAs issue the messaging
certificates too. Do not assume HTTPS success proves TLS on port 1414.

Controller SSH must reach the client as root using the existing trusted host key
and noninteractive key authentication. The fixed remote command uses `runuser`
to run Java as `mqtest`. This version does not translate arbitrary Ansible
ProxyJump/become/password settings; configure standard SSH accordingly. Passwords
are passed only on encrypted SSH stdin, never in command arguments or files.

## Local configuration and execution

```bash
git pull --ff-only
cp -n ansible/examples/mq-topology/audit.yml.example ansible/vars/mq-topology/audit.yml
vim ansible/vars/mq-topology/audit.yml
```

Set local endpoints/IPs and reviewed channel/protocol/cipher/peer parameters. Add separate
Vault client secrets; never use REST admin credentials as MQ client credentials.
Set `mq_topology_confirm_test_mutations: true` only after reviewing setup.
All site values stay in the ignored local directory. No VMID/IP is embedded.

```bash
ansible-playbook ansible/playbooks/mq-topology-audit.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/audit.yml --ask-vault-pass --syntax-check

ansible-playbook ansible/playbooks/mq-topology-audit.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e @ansible/vars/mq-topology/audit.yml --ask-vault-pass \
  -e "mq_audit_mail_to=${report_receiver:?Empfänger zuerst setzen}"
```

Omit the last option to disable mail. Each run creates a fresh BGT prefix and
stores `Pruefbericht.md`, `evidence.json` (including nested A/B object reports),
and `SHA256SUMS` under ignored `ansible/reports/mq-topology/`. Git revision,
UTC case times, client source/JAR checksums and exact MQ reason results are
included. Unknown error text is suppressed rather than leaking credentials.

The final assertion fails for FAIL **and PARTIAL**, after saving/mail submission.
Do not mistake this for a need to rerun repeatedly: inspect the report first.
Mail submission is not independently verified mailbox delivery. Hashes are not
signatures or independent timestamps. Provisioning/compilation failures before
the audit module starts do not produce a messaging audit report.

## Safety and time bounds

Every owned queue has a unique per-run name, MAXDEPTH ≤ 10 and MAXMSGL 4096.
No CLEAR, PURGE, REPLACE or FORCE. Nonempty/in-use residual queues stay in place.
After a 45-second remote probe timeout, further mutations stop and fixtures
remain, because the remote JVM may still run. Inspect/stop that exact process
before another audit. Individual GET waits are bounded to 10 seconds; expiry
uses a short controlled wait. One wrong-password attempt per node can still
affect account lockout counters; use dedicated test identities.

Compilation is checked using Java 17's compiler and standard APIs. IBM classes
are resolved through reflection at runtime to avoid bundling proprietary JARs.
The API preflight checks classes/constants, but actual MQ call compatibility
still needs live acceptance. Offline fake REST/probe tests are not live evidence.

The current IBM MQ 9.4/Java-client topology does not claim post-quantum TLS.
Quantum-safe negotiation remains a separately versioned MQ 10/C-client test
fixture and is not silently substituted for the enforced TLS 1.3 coverage.
