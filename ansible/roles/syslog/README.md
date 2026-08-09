# syslog

Central Syslog receiver for the Bergen Platform.

## Purpose

The role configures a Debian LXC as a central receiver for Syslog messages from
network devices, servers and appliances. It is intended as the first logging
layer for later Loki/Grafana and AI-assisted event correlation.

## Installed software

- rsyslog
- logrotate

## Services

By default the receiver listens on:

- UDP/514
- TCP/514

## Storage

Remote messages are stored by sender IP:

```text
/var/log/remote/<sender-ip>.log
```

This deliberately keeps the initial collector simple. Loki or another backend
can consume these files later without changing the Syslog sources.

## Variables

```yaml
syslog_remote_log_dir: /var/log/remote
syslog_udp_enabled: true
syslog_tcp_enabled: true
syslog_port: 514
syslog_retention_days: 90
```

## Deployment

First create and bootstrap the LXC using the existing Bergen Platform LXC
workflow. Add the resulting host to the `syslog_nodes` inventory group, then
run:

```bash
cd ~/bergen-platform
source bpenv/bin/activate
ansible-playbook ansible/playbooks/bootstrap-syslog.yml
```

Alternatively select another inventory target:

```bash
ansible-playbook ansible/playbooks/bootstrap-syslog.yml \
  -e bootstrap_syslog_target=my_syslog_host
```

## Configure sources

Configure routers, switches, access points and other appliances to send remote
Syslog to the LXC address on port 514. UDP is the broadest compatibility option;
TCP may be enabled where supported.

## Test

From a Linux host:

```bash
logger --server <SYSLOG-IP> --port 514 --udp "Bergen Platform Syslog Test"
```

On the collector:

```bash
ls -l /var/log/remote/
tail -f /var/log/remote/<SENDER-IP>.log
```

## Validation

```bash
rsyslogd -N1
ss -lntu | grep :514
systemctl status rsyslog
```

## Time synchronization

Reliable event correlation requires synchronized clocks. All Syslog sources and
Bergen Platform nodes should use NTP.

## Future integration

The collector is designed to be extended with:

1. Loki for indexed log access
2. Grafana for exploration and dashboards
3. Prometheus for metrics
4. MQTT/Smart Home time-series ingestion
5. anomaly detection
6. LLM-assisted event correlation and causal hypothesis generation
