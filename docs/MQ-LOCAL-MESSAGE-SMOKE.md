# Local MQ messaging smoke test

Run from the controller repository root after configuring BGT.CLIENT and LDAP
on both evaluation queue managers:

```sh
ansible-playbook ansible/playbooks/mq-local-message-smoke.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e mq_smoke_side=a --ask-vault-pass
ansible-playbook ansible/playbooks/mq-local-message-smoke.yml \
  -i ansible/inventory.yml -i ansible/inventory.local.yml \
  -e mq_smoke_side=b --ask-vault-pass
```

Uses vault_mq_test_a_password / vault_mq_test_b_password, existing client JARs
and the root-owned Java probe. Imports the authentication smoke preflight;
one intentional bad-password attempt occurs per run. Stops on the first
unexpected result. Credentials are sent on stdin with no_log, never in argv.

Each run creates one new BGT.LOCAL.<random> queue without REPLACE, records
its name in output, and grants PUT/GET/BROWSE/INQ only to the selected LDAP
group for that exact queue. Persistent 4096-byte messages exercise:
payload and message-ID roundtrip, PUT commit visibility, PUT rollback,
normal-disconnect commit, GET commit, GET rollback/backout count, browse,
correlation selection, FIFO and expiry.

An always block deletes only the queue successfully created by this run,
using NOPURGE AUTHREC(YES). It does not purge residual messages or delete a
queue after failed creation. A nonempty queue or failed cleanup fails the
play; retain its displayed name and inspect it before any further cleanup.
Successful cleanup is followed by an exact absence check.

This is a diagnostic smoke test, not the immutable audit report workflow.
PASS does not cover routing, restart/crash durability, mTLS, TLS downgrade,
PQC, or the complete two-queue-manager audit.
