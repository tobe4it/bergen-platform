# Paperless v2: SSH-Prozessprüfungen (Entwicklungsstufe PR #78)

Stand 15.10.2026: **Staging/Development, keine produktive Sendefreigabe**.
Der aktive Synology-Sender `synology_scan_sync.py`, seine
`sync.lock`, die 19 historischen v1-SENT-Receipts und alle
Scan-Originale bleiben unverändert.

## Ausgangslage

Nach offline bestätigten 30 Sitzungstests in PR #77, 19
Transfer-Nachweistests in PR #76 und 18 Empfängerprüfungen in PR #75
sind zwei unabhängige Hostprozesse erforderlich:

- **NAS**: `paperless-sync` führt die rsync-Übertragung in die
  v2-Stagingstruktur aus; der authentische OpenSSH-Hostschlüssel
  des Empfängers muss fest bekannt sein. Ein `exit 0` allein
  beweist niemals eine neue Datei.
- **Controller → venombox → LXC 126**: Der Controller prüft über
  einen separat authentifizierten SSH-Kanal innerhalb von
  `bergen-paperless` als `paperless-ingest` den exakten
  Inhalt, SHA-256, die Größe und Dateiberechtigungen.

Die bestehende Umgebung nutzt bereits Ansible-/Proxmox-Zugriffe.
Das technische Konto, seine SSH-Rechte und der Hostschlüssel für
eine direkte, nichtinteraktive Verbindung vom Controller zu
`venombox` sind **noch nicht für dieses neue Modul nachgewiesen**.

## Was PR #78 bereitstellt

Die neue Bibliothek
`ansible/files/paperless/v2_process_preflight.py` hat **keinen
Kommandozeilen-Einstieg** und wird durch kein produktives Playbook
aufgerufen.

**`build_rsync_plan(...)`** erzeugt ausschließlich die
Argumentliste eines möglichen, später gesondert zu autorisierenden
Sendens. Die Funktion startet **keinen** rsync-Prozess. Sie

- validiert eine vollständige nonce-gebundene PREPARED-Identität,
- verlangt einen privaten, einzigen regulären Snapshot mit dem
  exakt zugehörigen `nas-v2-<nonce>-<hash>.pdf`-Namen,
- prüft lokale Dateirechte, Größe und den echten SHA-256,
- verlangt einen privaten SSH-Schlüssel und ein geprüftes
  `known_hosts`-Verzeichnis beziehungsweise eine eigene
  `known_hosts`-Datei,
- erzeugt einen festen rsync-Aufruf mit `--ignore-existing`,
  `--chmod=F600`, `--out-format=%i %n`, festem Ziel-Scope
  und SSH-`StrictHostKeyChecking=yes`,
- verwendet keinen Shell-String für den rsync-Aufruf selbst.

**`run_readonly_receiver(...)`** kann bei bewusstem Aufruf
auf einem entsprechend eingerichteten Controller einen echten,
**ausschließlich lesenden** SSH-Prozess starten. Vor der
Empfängerprüfung folgen drei streng festgelegte Unteraufrufe
auf demselben geprüften SSH-Target:

1. `sudo -n /usr/sbin/pct config 126`: `bergen-paperless`,
   unprivilegierter LXC, kein unconfined-AppArmor.
2. `sudo -n /usr/sbin/pct status 126`: Container muss laufen.
3. `sudo -n /usr/sbin/pct exec 126 -- /usr/sbin/runuser -u
   paperless-ingest -- /usr/bin/python3 - <scope> <filename>
   <sha256> <size>`: Empfängerprüfskript ausschließlich per
   stdin, keine Installation.

Der Aufruf ist mit `BatchMode=yes`, `IdentitiesOnly=yes`,
`StrictHostKeyChecking=yes`, expliziter
`UserKnownHostsFile`, beschränkter Laufzeit und
`shell=False` vorgesehen. Unbekannte Gastkonfiguration,
fehlende Zugriffsrechte, nicht passende Belege, unerwartete
Ausgabe oder SSH-Fehler führen zum Abbruch. Ergebnisse enthalten
**niemals** `sent_authorized=true` oder
`source_delete_authorized=true`.

Die Empfängerprüfung ist **keine** authentifizierte NAS-rsync-Sitzung
und beweist auch nicht, dass die Datei neu angelegt wurde.
Ein erfolgreicher Prozessaufruf wäre zudem zunächst nur eine
Momentaufnahme und ersetzt nicht die Import-/ACL-Prüfung.

## Warum rsync noch nicht ausführbar ist

Für den späteren NAS-Prozess fehlt ein **dauerhaftes ATTEMPTED-
Ereignis**, das vor dem ersten Start des rsync-Prozesses
atomar unter `sync.lock` persistiert wird.

Allein `PREPARED` und das erneute Prüfen des Datenbestands
genügen nicht, wenn ein Prozess nach Beginn der Übertragung
abstürzt. Bei einem Wiederanlauf darf derselbe Transport
niemals ohne vorherige manuelle Reconciliation wiederholt werden.
Die Journalhistorie und das lesende Audit müssen eine solche
ATTEMPTED-Stufe erst ausdrücklich verstehen, bevor der Transport
tatsächlich integriert werden kann.

Auch die betriebliche Zuordnung der gesicherten SSH-Schlüssel,
das restriktive `sudo -n pct`-Recht sowie die tatsächlichen
rsync-Dateirechte des Empfängers müssen vor einem Live-Test
durch read-only Preflight bestätigt werden.

## Offline-Prüfung

Im neuen Branch ausführen:

```bash
python3 -m unittest discover -s tests -p 'test_paperless_v2_process_preflight.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_v2_session_offline.py' -q
python3 -m unittest discover -s tests -p 'test_paperless_v2_transfer_evidence_offline.py' -q
python3 -m unittest discover -s tests -p 'test_paperless_v2_receiver_readonly.py' -q
```

Die 25 neuen Tests mocken **alle** Systemprozessaufrufe und benutzen
nur temporäre lokale Dateien. Sie übertragen keine PDFs und stellen
keine SSH-Verbindung her.

**Sicherheitsgrenze:** PR #78 darf nicht mit einer Freigabe für
`SENT`, `IMPORTED`, Quarantäne, `unlink`, 30-Tage-Purge oder
einen Merge nach `main` verwechselt werden. Der Merge erfolgt
erst nach erfolgreicher End-to-End-Prüfung der sicheren Quelllöschung.
