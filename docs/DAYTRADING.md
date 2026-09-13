# Provider-neutral daytrading collector

This role deploys a paper-trading signal collector with one locally selected
market-data adapter. It never places orders. The public repository contains the
strategy and adapters, while the selected provider, instrument mappings and all
credentials remain local.

Supported adapters:

- `replay`: bundled synthetic data or a local JSON fixture; no network access.
- `alpaca`: official US Market Data REST API with a selectable entitled feed.
- `ibkr`: an authenticated IBKR Client Portal Gateway and locally entitled
  instruments identified by `conid`.

Use of an adapter does not grant data rights. The account owner must ensure that
the configured subscription permits automated/non-display processing, intraday
history, derived signals and retention.

## Local files

`ansible/inventory.local.yml` is maintained by LXC discovery and contains only
the effective host address. Do not put provider settings there.

Create the ignored local settings file:

```bash
cp ansible/group_vars/all/bergen-daytrade.yml.example \
  ansible/group_vars/all/bergen-daytrade.yml
vim ansible/group_vars/all/bergen-daytrade.yml
```

Select exactly one provider there:

```yaml
daytrading_data_provider: alpaca  # alpaca | ibkr | replay
```

Secrets have exactly one source of truth:

```bash
ansible-vault edit ansible/group_vars/all/vault.yml
```

```yaml
vault_daytrading_smtp_password: "ROTATED_PASSWORD"
vault_daytrading_alpaca_api_key_id: "ALPACA_KEY_ID"
vault_daytrading_alpaca_api_secret_key: "ALPACA_SECRET_KEY"
```

Ansible renders secrets into dedicated target files with mode `0400`. They are
never included in `/etc/bergen-daytrading.json`.

## Provider examples

### Offline replay

```yaml
daytrading_data_provider: replay
daytrading_timer_enabled: false
daytrading_candidate_mode: gap
daytrading_replay_source_file: ""  # bundled synthetic fixture
```

Replay is deliberately manual. A local fixture may replace the synthetic file;
it is copied to the LXC during deployment.

### Alpaca US/IEX

```yaml
daytrading_data_provider: alpaca
daytrading_candidate_mode: gap
daytrading_timer_enabled: true
daytrading_timer_on_calendar: "Mon..Fri *-*-* 09:25:00 America/New_York"
daytrading_market_timezone: America/New_York
daytrading_alpaca_feed: iex
daytrading_provider_symbols: []
```

With an empty symbol list, the adapter combines Alpaca's official most-active
and gainers screeners. A fixed local list such as `[AAPL, MSFT]` bypasses the
screener. The feed must match the account's data entitlement.

### IBKR/Xetra watchlist

```yaml
daytrading_data_provider: ibkr
daytrading_candidate_mode: watchlist
daytrading_timer_enabled: true
daytrading_market_timezone: Europe/Berlin
daytrading_timer_on_calendar: "Mon..Fri *-*-* 08:58:00 Europe/Berlin"
daytrading_candidate_window_start: "09:00:00"
daytrading_opening_range_start: "09:00:00"
daytrading_opening_range_end: "09:15:00"
daytrading_signal_window_end: "11:00:00"
daytrading_ibkr_base_url: https://IBKR_GATEWAY:5000/v1/api
daytrading_ibkr_verify_tls: false
daytrading_ibkr_instruments:
  - symbol: BMW
    conid: REPLACE_WITH_CONID
    description: BMW AG
    exchange: IBIS
```

The Client Portal Gateway login/session is managed outside this role. Disabling
TLS verification is intended only for its self-signed certificate on an
isolated local network; install a trusted certificate and enable verification
where possible.

## Deploy and test

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/daytrading-collector.yml \
  --ask-vault-pass
```

For initial LXC creation, omit the not-yet-created local inventory:

```bash
ansible-playbook \
  -i ansible/inventory.yml \
  ansible/playbooks/deploy-daytrading.yml \
  -e @ansible/group_vars/all/bergen-daytrade.yml \
  --ask-vault-pass
```

Test the selected provider without producing a signal:

```bash
ansible -i ansible/inventory.local.yml market_collectors -b -m command -a \
  '/usr/bin/python3 /opt/bergen/daytrading-collector/collector.py --config /etc/bergen-daytrading.json provider-test'
```

Run the synthetic replay or start a live session manually:

```bash
ansible -i ansible/inventory.local.yml market_collectors -b -m command -a \
  '/usr/bin/python3 /opt/bergen/daytrading-collector/collector.py --config /etc/bergen-daytrading.json run-session'
```

Test SMTP independently:

```bash
ansible -i ansible/inventory.local.yml market_collectors -b -m command -a \
  '/usr/bin/python3 /opt/bergen/daytrading-collector/collector.py --config /etc/bergen-daytrading.json mail-test'
```

Results are written atomically to
`/var/lib/bergen-daytrading/YYYY-MM-DD/entry-signal.json` and `latest.json`.
The timer is disabled by default and the weekday timer is not an exchange
holiday calendar; live operation therefore remains fail-closed on missing data.
