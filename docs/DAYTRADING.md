# Daytrading market-data collector

This role deploys a small, registration-free data collector for the forward-papertrading experiment.
It **does not place broker orders**.

## Data path

1. TradingView public US screener discovers pre-market stocks-in-play.
2. Yahoo Finance 1-minute chart data reconstructs the exact 09:30–09:45 ET opening range.
3. TradingView supplies live price, VWAP and relative volume after 09:45 ET.
4. A signal is emitted only when price is above opening-range high and VWAP, with the configured RVOL threshold.
5. The result is written as immutable JSON and can optionally be mailed through the local mail infrastructure.
6. Scalable Capital remains the later execution-quality check for availability, EUR quote/spread and whole-share sizing.

The collector deliberately fails closed: if exact 1-minute opening-range data are unavailable, it emits `data_error` rather than inventing a trade.

## Inventory

Add the target LXC/VM to the existing inventory:

```yaml
market_collectors:
  hosts:
    daytrade:
      ansible_host: 192.0.2.10   # replace with the real address
```

No LXC ID or IP is hard-coded in the role.

## Optional mail bridge

Set these in `group_vars/market_collectors.yml`, `host_vars/<host>.yml`, or the vault as appropriate:

```yaml
daytrading_email_enabled: true
daytrading_smtp_host: mail.bergen.intern
daytrading_smtp_port: 25
daytrading_email_from: daytrading@thebergens.net
daytrading_email_to: YOUR_REAL_RECIPIENT
```

If SMTP authentication is needed, keep the password in the existing Ansible vault:

```yaml
daytrading_smtp_username: "..."
daytrading_smtp_password: "{{ vault_daytrading_smtp_password }}"
```

## Deploy

```bash
cd ansible
ansible-playbook -i inventory.yml playbooks/daytrading-collector.yml
```

## Validate

```bash
systemctl status bergen-daytrading-collector.timer
systemctl list-timers bergen-daytrading-collector.timer
systemd-analyze calendar 'Mon..Fri *-*-* 09:25:00 America/New_York'

sudo -u daytrade /usr/bin/python3 \
  /opt/bergen/daytrading-collector/collector.py \
  --config /etc/bergen-daytrading.json self-test
```

A live run can be started manually with:

```bash
systemctl start bergen-daytrading-collector.service
journalctl -u bergen-daytrading-collector.service -f
```

## Output

Daily result:

```text
/var/lib/bergen-daytrading/YYYY-MM-DD/entry-signal.json
```

Latest result:

```text
/var/lib/bergen-daytrading/latest.json
```

Typical successful signal contains:

```json
{
  "status": "signal",
  "selected_signal": {
    "ticker": "PL",
    "signal_time": "2026-09-14T09:48:10-04:00",
    "price_usd": 16.42,
    "opening_range_high": 16.35,
    "opening_range_low": 15.71,
    "vwap": 16.18,
    "relative_volume": 3.7
  }
}
```

## Strategy defaults

The role currently preserves the week-1 rules:

- US common stocks
- long only
- pre-market gap > 2%
- price > USD 5
- pre-market volume > 100,000 shares
- RVOL >= 1.5
- opening range 09:30–09:45 ET
- signal requires price > OR high and price > VWAP
- two consecutive 10-second confirmations
- no new signal after 10:00 ET

All values are Ansible variables and can be changed for a later experiment without changing the collector code.

## Caveats

TradingView's scanner endpoint and Yahoo's chart endpoint are public but not contractual market-data APIs. The role therefore treats unavailable or malformed data as an error and does not fabricate a signal. For real-money trading, use a licensed broker/data-feed API and implement exchange-calendar/holiday handling and execution controls.
