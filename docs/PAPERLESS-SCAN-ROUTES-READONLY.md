# Paperless Scan-Routen: Offline-Vorprüfung

Nachfolger des **Routenvalidators** aus [PR #56](https://github.com/tobe4it/bergen-platform/pull/56). Der produktive Gruppen-Scanfluss über Synology-Watcher, SSH/rsync, Paperless-Importprüfung und geschütztes Originalarchiv wird dadurch **nicht** verändert.

Der Validator prüft ausschließlich geplante NAS-Quellen und Paperless-Empfangsziele: je eine explizite Route für `Eltern` und `Familie`, mindestens eine private Route `Privat/<Benutzer>`, eindeutige Namen und Ziele, keine ineinanderliegenden Quellen, keine relativen oder `..`-Pfade, keine Admin-Identität als privater Eigentümer.

```bash
cd ~/bergen-platform
cp docs/examples/paperless.scan-ingest.example.yml ansible/vars/paperless.scan-ingest.local.yml
chmod 600 ansible/vars/paperless.scan-ingest.local.yml
# Reale Quelle und Benutzernamen ausschließlich in ignorierter lokaler Datei prüfen.
python3 ansible/scripts/paperless_scan_map_preflight.py ansible/vars/paperless.scan-ingest.local.yml
python3 -m unittest discover -s tests -p 'test_paperless_scan_ingest.py' -v
```

Ein `PREFLIGHT_PASS` bestätigt **keine** DSM-ACL, keine existierenden LDAP-/Paperless-Konten, keine tatsächliche Senderkonfiguration, keine Dokumentzuordnung und keine Berechtigung zu Archivierung oder Löschung. Dieser Validator **legt keine Verzeichnisse an und importiert keine PDFs**. Wer neue private Benutzerbereiche einrichtet, benötigt einen separaten, standortunabhängigen Provisionierungs- und negativen Live-ACL-Test.

Die alte Synology-Rolle aus #56 wird bewusst **nicht** unverändert übernommen: Sie enthält fest eingebaute LDAP-Pfade, Benutzergruppen, eine NAS-Identität sowie schreibende ACL-/Synthetiktests. Für eine allgemeine Plattforminstallation muss diese Komponente vor dem Deployment neu entworfen werden.

ASN-Erkennung ist eine unabhängige Option des Greenfield-Backends und wird gesondert versioniert; sie ist kein Bestandteil des Routenvalidators und wird nicht automatisch aktiviert.
