# Paperless v2: Kontrollierte Einmalsitzung (nur Offline-Test)

Stand: 15.10.2026. **Entwicklung, keine Freigabe für die Synology oder den
produktiven Sender.** Der bereits aktive `synology_scan_sync.py` wird
nicht verändert. 19 bestätigte historische v1-`SENT`-Receipts bleiben
unverändert.

## Was jetzt abgedeckt ist

Die neue Bibliothek
`ansible/files/paperless/v2_sender_session_offline.py`
stellt `run_offline_once(...)` ausschließlich für kontrollierte
Testdateien und **injizierte Test-Callbacks** bereit.

Unter dem bereits bestehenden exklusiven `sync.lock`:

1. Der komplette vorhandene v1/v2-Journalbestand wird vorab geprüft.
   Ein bereits bekanntes Paar aus Scope und Quelldateiname oder ein
   unvollständiges/unerwartetes Journal sperrt den Vorgang.
2. Ein lokal lesbares, einzelnes reguläres PDF mit UID des
   ausführenden Testprozesses und Modus `0600` wird durch
   `O_NOFOLLOW`, Größen- und Signaturprüfung in ein privates
   temporäres Verzeichnis kopiert. Die temporäre Snapshot-Kopie
   wird mit `fsync` persistiert und per SHA-256 geprüft.
3. Unter derselben Sperre wird eine kryptografische 128-Bit-Nonce
   generiert und das komplette `PREPARED`-Ereignis per
   unveränderlicher Create-only-Publikation auf Datenträger
   geschrieben und überprüft. **Vorher darf kein Transport beginnen.**
4. Ein injizierter **Test-Transport-Callback** bekommt nur den
   eingefrorenen PDF-Snapshot und die zugehörige
   `PREPARED`-Identität. Die Rückgabewerte werden auf genau einen
   rsync-Neudatei-Marker geprüft.
5. Nur danach läuft ein getrennter **Test-Empfänger-Callback**.
   Seine vollständig gebundene Prüfausgabe wird mit dem
   `PREPARED`-Eintrag, der SHA-256-Prüfsumme und Größe verglichen.
6. Nach beiden Callbacks wird der unveränderliche
   `PREPARED`-Eintrag erneut gelesen. Quelle und eingefrorener
   Snapshot werden auf ursprüngliche Identität und Hash geprüft.
7. Die Bibliothek kehrt **immer ohne SENT-Freigabe** zurück.
   Das `PREPARED`-Receipt verbleibt im Journal und sperrt
   eine weitere automatische Ausführung desselben Quelldateinamens.

Die Sendersperre bleibt über den gesamten Testablauf gehalten.
Das wirkt parallelen Senderläufen entgegen, ist aber erst nach
Prüfung aller beteiligten DSM-Prozesse eine produktive Garantie.

## Sicherheitsentscheidung bei Abstürzen

| Zeitpunkt der Unterbrechung | Verbleibender Zustand | Automatischer Wiederholungsversuch |
|---|---|---|
| Vor dauerhaftem PREPARED | Kein gültiger Übertragungsnachweis | Keine laufende Sitzung |
| Nach PREPARED, vor Transport-Callback | PREPARED ohne SENT | **Gesperrt** |
| Nach Transport, vor Empfängerprüfung | PREPARED ohne SENT | **Gesperrt** |
| Nach positiver Empfängerprüfung | PREPARED ohne SENT | **Gesperrt** |
| Dateisignatur, Snapshot oder Receipt verändert | Abbruch und PREPARED | **Gesperrt** |

Ein nachträgliches `SENT` darf nur eine eigenständige, überprüfte
Implementierung mit authentischer Prozessherkunft und dauerhaftem
`PREPARED`-Abgleich erteilen. Die nun getesteten Callbacks können
beliebige Resultate vortäuschen. Aus ihrem Erfolg darf **nie** eine
produktive Berechtigung abgeleitet werden.

## Prüfungen auf bp-controller

```bash
python3 -m unittest discover -s tests -p 'test_paperless_v2_session_offline.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_v2_transfer_evidence_offline.py' -v
python3 -m unittest discover -s tests -p 'test_paperless_v2_receiver_readonly.py' -v
```

Die neue Suite umfasst 29 Tests (noch auf dem Controller auszuführen):
dauerhaftes PREPARED, Namenswiederholung, simulierte Abstürze,
falscher oder fehlender rsync-Marker, Quell- und Snapshot-Manipulation
zwischen den Prüfschritten, falsche Empfängerbestätigung,
Sperrenkonkurrenz, beschädigtes Journal, private Quelldatei und
eingeschränkte Scope-Auswahl.

## Weiterhin blockiert

- Echte Ausführung des rsync-Prozesses durch einen vertrauenswürdigen,
  auf DSM gehärteten Prozess mit überprüftem SSH-Hostschlüssel
  und Empfänger-Zielpfad.
- Sicherer Aufruf des LXC-126-Empfängerprüfers über den
  authentifizierten Proxmox-Steuerkanal; keine Übernahme frei
  eingesandter Nachweistexte.
- Empfängerseitige sichere `0600`-Publikation durch
  `paperless-ingest`, ohne Überschreiben vorhandener Dateien.
- Strenges und getestetes Verfahren für aufgelöste, dauerhaft
  protokollierte PREPARED-Abbrüche; es gibt **keine** blinde
  Wiederholung und kein automatisches `SENT`.
- Verifizierter Paperless-`IMPORTED`-Status samt
  Benutzeridentität, Scope, effektiven ACLs und absichtlichen
  Benutzerlöschungen.
- Sichere private Quarantäne über die NAS-Btrfs-Subvolume-Grenze,
  Kopie plus Dateisynchronisation/Hashnachweis, kontrolliertes
  `unlink`, Wiederherstellungsprobe und 30-Tage-/Backup-Prüfung.

**Weder Quelllöschung noch 30-Tage-Bereinigung noch Merge nach
`main` ist derzeit autorisiert.**
