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

## Preconditions before any apply

1. Verify that both MQ server certificates/peer trust chains work for the
   intended **SDR/RCVR** TLS handshake. Independent CA certificates are in
   use on A and B; trusting only the local CA or merely copying a CA to the
   controller does **not** configure the peer queue manager's MQ trust store.
2. Verify source-specific TCP/1414 firewall access from A to B and B to A,
   **both** runtime and permanent, plus any Proxmox/UniFi policy. Existing
   firewall automation currently adds only the client source, not the peer.
3. Review channel CHLAUTH/MCAUSER and minimum authorities for the receiving
   destination queues. Do not disable CHLAUTH or use privileged MCA identities.
4. Obtain explicit change authorization for creating the six objects.
   This playbook does **not** start the new sender channels.

Only after these independent checks, a live run requires all three opt-ins:
`mq_transport_confirm_apply=true`,
`mq_transport_peer_firewall_verified=true` and
`mq_transport_cross_ca_verified=true`. These are **operator attestations**,
not automated proof. Run the same playbook without `--check` and rerun
`--check --diff` to verify idempotence.

## Audit integration

After both channels are securely established and running, the site-local,
Git-ignored `ansible/vars/mq-topology/audit.yml` must contain:

```yaml
# mq_topology_nodes.a:
sender_channel: BGT.A2B
xmitq: BGT.XMIT.A2B

# mq_topology_nodes.b:
sender_channel: BGT.B2A
xmitq: BGT.XMIT.B2A
```

These are **nested** values under the respective node, not top-level keys.
The `denied_queue` settings are independent: leave empty until a verified
`BGT.DENIED*` negative-authorization fixture exists; otherwise OAM negative
coverage remains NOT_TESTED.

The topology audit creates unique temporary local/remote queues and deletes
only its owned objects when safe. It does not create or activate these
persistent channel/XMITQ fixtures. Review actual A→B and B→A results (five
remote variants per side) rather than accepting a generic PARTIAL status as
proof of routing.
