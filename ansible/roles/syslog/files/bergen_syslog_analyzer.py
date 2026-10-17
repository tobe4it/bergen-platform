#!/usr/bin/env python3
import argparse
import fcntl
import glob
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

DB = os.environ.get('BERGEN_ANALYZER_DB', '/var/lib/bergen-syslog/analyzer.db')
LOG_GLOB = os.environ.get('BERGEN_REMOTE_LOG_GLOB', '/var/log/remote/*.log')
LOCK = os.environ.get('BERGEN_ANALYZER_LOCK', '/var/lib/bergen-syslog/analyzer.lock')
MAC_RE = re.compile(r'(?i)\b([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b')
TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2}))')
RSSI_RE = re.compile(r'(?i)(?:auth_rssi["=: ]+|\brssi["=: ]+)(-?\d+)')

EVENTS = [
    ('wpa_handshake_start', re.compile(r'WPA: sending 1/4 msg of 4-Way Handshake', re.I)),
    ('wpa_invalid_state', re.compile(r'received EAPOL-Key msg 4/4 in invalid state', re.I)),
    ('eapol_timeout', re.compile(r'EAPOL-Key timeout', re.I)),
    ('sta_leave', re.compile(r'EVENT_STA_LEAVE|sta left', re.I)),
    ('associated', re.compile(r'IEEE 802\.11: associated', re.I)),
    ('authenticated', re.compile(r'IEEE 802\.11: authenticated|authentication OK', re.I)),
    ('disassociated', re.compile(r'IEEE 802\.11: disassociated|trying to disassociate', re.I)),
]

def connect():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB, timeout=30)
    db.execute('PRAGMA busy_timeout=30000')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS offsets(path TEXT PRIMARY KEY, inode INTEGER, pos INTEGER);
      CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT, source TEXT, mac TEXT, kind TEXT, rssi INTEGER, raw TEXT);
      CREATE INDEX IF NOT EXISTS idx_events_mac_ts ON events(mac, ts);
      CREATE TABLE IF NOT EXISTS incidents(mac TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, severity TEXT, event_count INTEGER, handshake_failures INTEGER, eapol_timeouts INTEGER, leaves INTEGER, sources TEXT, summary TEXT);
    ''')
    return db

def classify(line):
    mac = MAC_RE.search(line)
    if not mac:
        return None
    kind = None
    for name, rx in EVENTS:
        if rx.search(line):
            kind = name
            break
    if not kind:
        return None
    ts = TS_RE.search(line)
    rssi = RSSI_RE.search(line)
    return (ts.group(1) if ts else datetime.now(timezone.utc).isoformat(), mac.group(1).lower(), kind, int(rssi.group(1)) if rssi else None)

def ingest(db):
    added = 0
    for path in glob.glob(LOG_GLOB):
        try:
            st = os.stat(path)
            row = db.execute('SELECT inode,pos FROM offsets WHERE path=?', (path,)).fetchone()
            pos = row[1] if row and row[0] == st.st_ino and row[1] <= st.st_size else 0
            with open(path, 'r', errors='replace') as f:
                f.seek(pos)
                for line in f:
                    parsed = classify(line)
                    if parsed:
                        ts, mac, kind, rssi = parsed
                        db.execute('INSERT INTO events(ts,source,mac,kind,rssi,raw) VALUES(?,?,?,?,?,?)', (ts, os.path.basename(path), mac, kind, rssi, line.rstrip()))
                        added += 1
                pos = f.tell()
            db.execute('INSERT INTO offsets(path,inode,pos) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET inode=excluded.inode,pos=excluded.pos', (path, st.st_ino, pos))
        except (OSError, UnicodeError):
            continue
    db.commit()
    correlate(db)
    return added

def correlate(db):
    macs = [r[0] for r in db.execute("SELECT DISTINCT mac FROM events WHERE ts >= datetime('now','-24 hours')")]
    for mac in macs:
        rows = db.execute("SELECT ts,source,kind,rssi FROM events WHERE mac=? AND ts >= datetime('now','-24 hours') ORDER BY ts", (mac,)).fetchall()
        if not rows:
            continue
        invalid = sum(r[2] == 'wpa_invalid_state' for r in rows)
        timeouts = sum(r[2] == 'eapol_timeout' for r in rows)
        leaves = sum(r[2] == 'sta_leave' for r in rows)
        sources = sorted(set(r[1] for r in rows))
        bad = invalid + timeouts
        if bad >= 10 or (bad >= 5 and len(sources) >= 2): severity = 'ACTION'
        elif bad >= 3: severity = 'OBSERVE'
        else: severity = 'INFO'
        summary = f'{bad} WPA/EAPOL failures, {leaves} leave events, {len(sources)} source(s) in last 24h'
        db.execute('''INSERT INTO incidents(mac,first_seen,last_seen,severity,event_count,handshake_failures,eapol_timeouts,leaves,sources,summary)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mac) DO UPDATE SET first_seen=excluded.first_seen,last_seen=excluded.last_seen,severity=excluded.severity,event_count=excluded.event_count,handshake_failures=excluded.handshake_failures,eapol_timeouts=excluded.eapol_timeouts,leaves=excluded.leaves,sources=excluded.sources,summary=excluded.summary''',
          (mac, rows[0][0], rows[-1][0], severity, len(rows), invalid, timeouts, leaves, json.dumps(sources), summary))
    db.commit()

def list_incidents(db, severity=None):
    q = 'SELECT severity,mac,last_seen,summary FROM incidents'
    args = []
    if severity:
        q += ' WHERE severity=?'; args.append(severity)
    q += " ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'ACTION' THEN 1 WHEN 'OBSERVE' THEN 2 ELSE 3 END,last_seen DESC"
    for row in db.execute(q, args):
        print(f'{row[0]:8} {row[1]}  {row[2]}  {row[3]}')

def show(db, mac):
    row = db.execute('SELECT * FROM incidents WHERE mac=?', (mac.lower(),)).fetchone()
    if not row:
        raise SystemExit('incident/client not found')
    cols = [d[0] for d in db.execute('SELECT * FROM incidents LIMIT 0').description]
    print(json.dumps(dict(zip(cols,row)), indent=2))
    print('\nRecent evidence:')
    for ts,source,kind,rssi,raw in db.execute('SELECT ts,source,kind,rssi,raw FROM events WHERE mac=? ORDER BY id DESC LIMIT 25', (mac.lower(),)):
        print(f'{ts} {source} {kind} rssi={rssi if rssi is not None else "-"}\n  {raw}')

def advise(db, mac):
    """Read-only, evidence-bound advisory; never change WLAN or service state."""
    mac = mac.lower()
    row = db.execute('SELECT severity,first_seen,last_seen,handshake_failures,eapol_timeouts,leaves,sources FROM incidents WHERE mac=?', (mac,)).fetchone()
    if row is None:
        raise SystemExit('incident/client not found')
    severity, first_seen, last_seen, handshakes, timeouts, leaves, sources_json = row
    try:
        sources = json.loads(sources_json or '[]')
    except (ValueError, TypeError):
        sources = []
    source_count = len(sources) if isinstance(sources, list) else 0
    failures = int(handshakes or 0) + int(timeouts or 0)
    leaves = int(leaves or 0)

    # Use only bounded recent observations; do not print raw log lines or AP names.
    values = [r[0] for r in db.execute(
        "SELECT rssi FROM events WHERE mac=? AND rssi BETWEEN -110 AND -1 "
        "AND ts >= datetime('now','-24 hours') ORDER BY id DESC LIMIT 500",
        (mac,))]
    print(f'{severity} – WLAN-Diagnose zu {mac}')
    print(f'Erfasster Vorfall: {first_seen} bis {last_seen}.')
    print(f'Korrelation: {failures} WPA/EAPOL-Fehler, {leaves} Leave-Ereignisse, '
          f'{source_count} Logquelle(n).')
    if source_count >= 2:
        print('Mehrere Quellen sind betroffen; ein einzelner Access Point '
              'ist als alleinige Ursache nicht belegt.')
    if values:
        mean = sum(values) / len(values)
        print(f'RSSI aus {len(values)} jüngeren gültigen Messungen: '
              f'Mittel {mean:.0f} dBm, Spanne {min(values)} bis {max(values)} dBm.')
        if mean <= -72:
            print('Funkabdeckung oder Roaming als mögliche Mitursachen prüfen.')
        else:
            print('Ein dauerhaft schwaches Signal ist aus diesen Werten nicht belegt.')
    else:
        print('Keine verwertbaren jüngeren RSSI-Werte; Signalqualität unbekannt.')
    if severity == 'ACTION':
        print('Empfehlung: Client und zugeordnete APs identifizieren, '
              'SSID/Sicherheit und mögliche Roaming-Wechsel prüfen. '
              'Keine Kanal- oder Leistungsänderung allein aus dieser Auswertung.')
    elif severity == 'OBSERVE':
        print('Empfehlung: Fehlerentwicklung beobachten; noch nichts ändern.')
    else:
        print('Empfehlung: Kein automatischer Eingriff; Evidenz bei Bedarf erneut prüfen.')
    print('Konfidenz: Ereignismuster aus gespeicherten Logs; Ursache und '
          'zeitliche Vollständigkeit nicht unabhängig bestätigt. '
          'Keine automatische Konfigurationsänderung.')


def run_locked(db):
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, 'w') as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('analyzer run already in progress; skipping')
            return 0
        return ingest(db)

def main():
    p=argparse.ArgumentParser(description='Bergen Syslog Operations Analyzer')
    sub=p.add_subparsers(dest='cmd')
    sub.add_parser('run-once')
    lp=sub.add_parser('list'); lp.add_argument('--severity', choices=['INFO','OBSERVE','ACTION','CRITICAL'])
    sp=sub.add_parser('show'); sp.add_argument('mac')
    ap=sub.add_parser('advise'); ap.add_argument('mac')
    args=p.parse_args(); db=connect()
    if args.cmd=='run-once': print(f'ingested {run_locked(db)} normalized events')
    elif args.cmd=='list': list_incidents(db,args.severity)
    elif args.cmd=='show': show(db,args.mac)
    elif args.cmd=='advise': advise(db,args.mac)
    else: p.print_help()

if __name__ == '__main__': main()
