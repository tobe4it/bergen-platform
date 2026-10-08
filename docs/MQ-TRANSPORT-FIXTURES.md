# Bergen MQ bidirectional transport fixtures (evaluation only)

This playbook prepares **only** the isolated MQ objects needed by the existing
topology audit. It does **not** start MQ channels, grant authority, import
trust anchors, open TCP ports or run a live audit.

## Dedicated topology

| Queue manager | Transmission queue | Sender | Receiver for opposite direction |
| --- | --- | --- | --- |
| BERGENLAB (A) | `BGT.XMIT.A2B` | `BGT.A2B` → B | `BGT.B2A` |
| BERGENLABB (B) | `BGT.XMIT.B2A` | `BGT.B2A` → A | `BGT.A2B` |

Both channel pairs declare `TLS_AES_256_GCM_SHA384`. The server certificate
and receiving CA trust must already be configured and verified; declaring
`SSLCIPH` does not establish a successful TLS connection. The audit requires
the sender channel to be running for each transport case.

The bounded `mq_objects` REST reconciler never prunes omitted objects,
refuses channel/queue type conversion, and verifies post-change DISPLAY.
It cannot perform MQ channel start/stop or CHLAUTH/OAM changes.

## Read-only preview (mandatory first step)

Use the existing **ignored local** audit variables and encrypted Vault:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/mq-transport-objects.yml \
  -e @ansible/vars/mq-topology/audit.yml \
  --check --diff --ask-vault-pass
```

Review the two QMgr plans, object-name collisions and existing attributes.
Do not apply if an existing `BGT.*` name is owned by another workload.

## Pending redesign: per-run transport fixtures

The initial PR proposed persistent `BGT.A2B`/`BGT.B2A` channels and XMITQs.
That is not the desired audit model. **The current playbook is now restricted
to Ansible check mode and must not be used for live deployment.**

The next implementation must integrate fixture ownership into
`bergen_mq_topology.run()` and its evidence:

1. Preflight exact lab identities, TLS peer CA trust, source-specific A↔B
   TCP/1414 connectivity and reviewed CHLAUTH/OAM. Do not change global rules.
2. Generate unique bounded `BGT.<RUN_ID>.*` channel and XMITQ names for
   each direction. Refuse *any* pre-existing object collision.
3. On each queue manager, DEFINE only owned XMITQ, SDR and matching RCVR,
   with TLS 1.3 cipher and explicit peer endpoint. Track each successfully
   created identity immediately so partial failures remain visible.
4. START only the run-owned sender channels and verify channel state and
   negotiated TLS before sending test messages.
5. Create run-owned QREMOTE and QLOCAL fixtures; verify message payload,
   ID, persistence, commit and rollback from A→B and B→A.
6. In a bounded finalizer, STOP only owned senders with QUIESCE, verify no
   active channel and no outstanding/in-doubt messages, delete only empty
   run-owned queues and run-owned channels, and verify absence.
7. If channel stop times out, message delivery is uncertain or a queue is
   nonempty/in use: fail the audit and **retain** unsafe objects for manual
   investigation. Never use FORCE/PURGE/CLEAR or auto-retry the unknown
   outcome.

All temporary object identities, transport results, cleanup attempts and
residuals belong in `evidence.json` and `Pruefbericht.md`.
`PARTIAL` may indicate deferred *unimplemented* cases, not successful
transport where transport was never exercised.

Reference: IBM MQ JSON MQSC REST supports `start` and `stop` commands,
but channel-state transitions need explicit, bounded verification.
No live inter-QMgr tests have been run using this PR.

## Read-only planning

The available draft playbook can only generate a desired-object preview:

```bash
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \\
  ansible/playbooks/mq-transport-objects.yml \\
  -e @ansible/vars/mq-topology/audit.yml \\
  --check --diff --ask-vault-pass
```

Its static object names are **not** suitable for live audit use. Do not
merge this draft until the per-run lifecycle and regression tests replace
this prototype.
