#!/usr/bin/env python3
import argparse
import fcntl
import glob
import json
import os
import re
import sqlite3
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
    if not mac: return None
    kind = next((name for name, rx in EVENTS if rx.search(line)), None)
    if not kind: return None
    ts = TS_RE.search(line); rssi = RSSI_RE.search(line)
    return (ts.group(1) if ts else datetime.now(timezone.utc).isoformat(), mac.group(1).lower(), kind, int(rssi.group(1)) if rssi else None)

def ingest(db):
    added = 0
    for path in glob.glob(LOG_GLOB):
        try:
            st = os.stat(path); row = db.execute('SELECT inode,pos FROM offsets WHERE path=?', (path,)).fetchone()
            pos = row[1] if row and row[0] == st.st_ino and row[1] <= st.st_size else 0
            with open(path, 'r', errors='replace') as f:
                f.seek(pos)
                for line in f:
                    parsed = classify(line)
                    if parsed:
                        ts, mac, kind, rssi = parsed
                        db.execute('INSERT INTO events(ts,source,mac,kind,rssi,raw) VALUES(?,?,?,?,?,?)', (ts, os.path.basename(path), mac, kind, rssi, line.rstrip())); added += 1
                pos = f.tell()
            db.execute('INSERT INTO offsets(path,inode,pos) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET inode=excluded.inode,pos=excluded.pos', (path, st.st_ino, pos))
        except (OSError, UnicodeError): continue
    db.commit(); correlate(db); return added

def correlate(db):
    macs = [r[0] for r in db.execute("SELECT DISTINCT mac FROM events WHERE ts >= datetime('now','-24 hours')")]
    for mac in macs:
        rows = db.execute("SELECT ts,source,kind,rssi FROM events WHERE mac=? AND ts >= datetime('now','-24 hours') ORDER BY ts", (mac,)).fetchall()
        if not rows: continue
        invalid=sum(r[2]=='wpa_invalid_state' for r in rows); timeouts=sum(r[2]=='eapol_timeout' for r in rows); leaves=sum(r[2]=='sta_leave' for r in rows)
        sources=sorted(set(r[1] for r in rows)); bad=invalid+timeouts
        severity='ACTION' if bad>=10 or (bad>=5 and len(sources)>=2) else 'OBSERVE' if bad>=3 else 'INFO'
        summary=f'{bad} WPA/EAPOL failures, {leaves} leave events, {len(sources)} source(s) in last 24h'
        db.execute('''INSERT INTO incidents(mac,first_seen,last_seen,severity,event_count,handshake_failures,eapol_timeouts,leaves,sources,summary) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mac) DO UPDATE SET first_seen=excluded.first_seen,last_seen=excluded.last_seen,severity=excluded.severity,event_count=excluded.event_count,handshake_failures=excluded.handshake_failures,eapol_timeouts=excluded.eapol_timeouts,leaves=excluded.leaves,sources=excluded.sources,summary=excluded.summary''',(mac,rows[0][0],rows[-1][0],severity,len(rows),invalid,timeouts,leaves,json.dumps(sources),summary))
    db.commit()

def list_incidents(db,severity=None):
    q='SELECT severity,mac,last_seen,summary FROM incidents'; args=[]
    if severity: q+=' WHERE severity=?'; args.append(severity)
    q+=" ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'ACTION' THEN 1 WHEN 'OBSERVE' THEN 2 ELSE 3 END,last_seen DESC"
    for row in db.execute(q,args): print(f'{row[0]:8} {row[1]}  {row[2]}  {row[3]}')

def incident(db,mac):
    row=db.execute('SELECT * FROM incidents WHERE mac=?',(mac.lower(),)).fetchone()
    if not row: raise SystemExit('incident/client not found')
    cols=[d[0] for d in db.execute('SELECT * FROM incidents LIMIT 0').description]
    return dict(zip(cols,row))

def show(db,mac):
    print(json.dumps(incident(db,mac),indent=2)); print('\nRecent evidence:')
    for ts,source,kind,rssi,raw in db.execute('SELECT ts,source,kind,rssi,raw FROM events WHERE mac=? ORDER BY id DESC LIMIT 25',(mac.lower(),)):
        print(f'{ts} {source} {kind} rssi={rssi if rssi is not None else "-"}\n  {raw}')

def advise(db,mac):
    i=incident(db,mac); sources=json.loads(i['sources'] or '[]'); bad=i['handshake_failures']+i['eapol_timeouts']
    rssis=[r[0] for r in db.execute("SELECT rssi FROM events WHERE mac=? AND rssi IS NOT NULL AND ts >= datetime('now','-24 hours')",(mac.lower(),)).fetchall()]
    print(f"{i['severity']} – WLAN-Verbindung von {mac.lower()}\n")
    if bad:
        print(f"Der Client fällt seit {i['first_seen']} durch wiederholte WPA/EAPOL-Probleme auf. In den letzten 24 Stunden habe ich {bad} fehlgeschlagene bzw. inkonsistente Handshake-Ereignisse und {i['leaves']} Verbindungsabbrüche/Leave-Ereignisse gesehen.")
    else:
        print(f"Ich sehe für den Client derzeit keine gehäuften WPA/EAPOL-Fehler. Es gab {i['leaves']} Leave-Ereignisse in den letzten 24 Stunden.")
    if len(sources)>=2:
        print(f"\nDas Verhalten wurde in {len(sources)} unterschiedlichen Logquellen beobachtet ({', '.join(sources)}). Deshalb halte ich einen einzelnen Access Point als alleinige Ursache momentan für eher unwahrscheinlich.")
    if rssis:
        neg=[x for x in rssis if x<0]
        if neg:
            avg=sum(neg)/len(neg); print(f"\nDie verwertbaren RSSI-Werte liegen im Mittel bei {avg:.0f} dBm (Spanne {min(neg)} bis {max(neg)} dBm)." + (" Das ist schwach genug, dass Funkabdeckung oder Roaming mitursächlich sein können." if avg<=-72 else " Das spricht nicht für ein durchgehend schwaches Funksignal als alleinige Erklärung."))
    print('\nMeine Empfehlung:')
    if i['severity']=='ACTION':
        if len(sources)>=2:
            print('Identifiziere zuerst das Gerät und prüfe, ob es stationär ist sowie welche SSID und WLAN-Sicherheitsoptionen es verwendet. An Kanalwahl oder Sendeleistung würde ich aufgrund dieser Daten noch nichts ändern. Wenn das Gerät stationär ist, würde ich anschließend prüfen, warum es zwischen mehreren APs wechselt und ob Fast Roaming bzw. die AP-Auswahl beteiligt ist.')
        else:
            print('Prüfe zuerst den betroffenen Client und den zugehörigen Access Point. Für eine konkrete Konfigurationsänderung reichen mir die Daten noch nicht; ich würde insbesondere Signalstärke und Wiederholbarkeit beobachten.')
    elif i['severity']=='OBSERVE':
        print('Noch nichts ändern. Das Muster ist auffällig, aber für einen Eingriff noch nicht belastbar genug. Ich würde beobachten, ob die Fehlerzahl weiter steigt oder weitere APs betroffen sind.')
    else:
        print('Aktuell kein Eingriff. Die beobachteten Ereignisse liegen unter meiner Handlungsschwelle.')
    print('\nEinschätzung: ' + ('reales wiederkehrendes Problem; Ursache noch nicht sicher genug für eine automatische Konfigurationsänderung.' if i['severity']=='ACTION' else 'weiter beobachten; derzeit keine belastbare Konfigurationsänderung ableitbar.'))

def run_locked(db):
    os.makedirs(os.path.dirname(LOCK),exist_ok=True)
    with open(LOCK,'w') as lockfile:
        try: fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: print('analyzer run already in progress; skipping'); return 0
        return ingest(db)

def main():
    p=argparse.ArgumentParser(description='Bergen Syslog Operations Analyzer'); sub=p.add_subparsers(dest='cmd'); sub.add_parser('run-once')
    lp=sub.add_parser('list'); lp.add_argument('--severity',choices=['INFO','OBSERVE','ACTION','CRITICAL'])
    sp=sub.add_parser('show'); sp.add_argument('mac'); ap=sub.add_parser('advise'); ap.add_argument('mac')
    args=p.parse_args(); db=connect()
    if args.cmd=='run-once': print(f'ingested {run_locked(db)} normalized events')
    elif args.cmd=='list': list_incidents(db,args.severity)
    elif args.cmd=='show': show(db,args.mac)
    elif args.cmd=='advise': advise(db,args.mac)
    else: p.print_help()
if __name__=='__main__': main()
