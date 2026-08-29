# remote_syslog

Configures a supported Linux host to forward its local Syslog stream to the
central Bergen Syslog collector.

## Defaults

```yaml
remote_syslog_enabled: true
remote_syslog_server: 192.168.20.164
remote_syslog_port: 514
remote_syslog_protocol: tcp
remote_syslog_config_path: /etc/rsyslog.d/90-bergen-remote.conf
remote_syslog_queue_size: 10000
remote_syslog_send_test: true
```

The forwarder uses an rsyslog linked-list action queue and retries indefinitely
while the collector is unavailable. Service logs continue locally according to
the host's normal logging policy.

## Verification

A role run validates the effective rsyslog configuration and emits one event
with tag `BERGEN-SYSLOG-TEST`. On the collector, verify the source file and
mail-service events:

```bash
grep BERGEN-SYSLOG-TEST /var/log/remote/<SOURCE-IP>.log
grep -E 'postfix|dovecot' /var/log/remote/<SOURCE-IP>.log | tail
```
