# BookStack: Implementierungs-, Abnahme- und Rollbackplan

Stand: DESIGN ONLY · 2026-10-18. **Keine Ansible-Apply-Ausführung** und keine Tests gegen produktive Hosts durch dieses Dokument.

## 0. Guardrails

- Dieses Paket beschreibt die künftige Implementierung; es provisioniert keine Instanz und ändert keine OIDC-, DNS-, Proxy-, NFS-, Paperless-, Bergen-AI- oder Foswiki-Konfiguration.
- Immer Feature-Branch, Review und explizite Betriebsfreigabe. Keine schreibenden Aufgaben auf main oder auf Produktivhosts als Nebeneffekt eines Audits.
- Frühzeitige Guard-Assertions: gewünschte Host-Identität, eindeutige VMID, Version-Pin, erreichbare repo-/Paket-Quelle, Quota, freie Kapazität, vertrauenswürdige Host-Keys, Backend-DNS und TLS-Eignung.
- Secret-Verarbeitung ausschließlich über Site-local-Vars/Vault; Ansible no_log für Token/Passwörter/Dumps; keine realen Domains/IPs im generischen Code.
- Wiederverwendbare eigenständige Rollen ohne imports aus paperless, bergen-ai, open-webui oder sonstigen Anwendungsrollen.
- Bei Konflikten mit vorhandenen LXC/Daten **hart abbrechen**, niemals einen bestehenden Container übernehmen oder löschen.
- Alte Wiki-VMID 114 unverändert; VMIDs 800–899 für historische Übernahmen reserviert.

## 1. Vorgesehene IaC-Artefakte (erst im Implementierungs-PR)

    ansible/playbooks/validate-bookstack-preflight.yml
    ansible/playbooks/create-bookstack-lxc.yml
    ansible/playbooks/manage-bookstack-runtime.yml
    ansible/playbooks/manage-bookstack-policy.yml
    ansible/playbooks/validate-bookstack.yml
    ansible/playbooks/backup-bookstack.yml
    ansible/playbooks/restore-bookstack-isolated.yml
    ansible/roles/bookstack-runtime/
    ansible/roles/bookstack-policy/
    ansible/roles/bookstack-backup/
    ansible/group_vars/all/bookstack.local.yml.example
    tests/bookstack/

Die Rollen sind getrennt:
- bookstack-runtime: Pakete/PHP-FPM/Nginx/DB, Release, .env, Datei-/Dienstrechte, Migrationen und Health.
- bookstack-policy: Rollen-/Buchmodell, Gruppenzuordnung, Audit/Drift und optional explizite ACL-Konfiguration.
- bookstack-backup: konsistente Daten-Sicherung/Restore-Manifest, Zeitpläne, Integritäts- und Kapazitätsgates.
- LXC-Provisionierung über vorhandene isolierte Proxmox-Baseline; keine eigene ungeprüfte SSH-Umgehung.

Berechtigungsänderungen sind nicht automatisch idempotent, nur weil man sie dokumentiert. Vor Ansible-Automatisierung des Policy-Writes die offiziell unterstützte BookStack-Verwaltungsoberfläche/APIs überprüfen. Falls Rollen/Content-ACL über API nicht abgedeckt sind: initial gesicherter administrativer Einrichtungsschritt, darauf Read-only-Driftaudit; **keine** direkten SQL-Rechteänderungen als Ersatz. Separater Approval-Gate für jeden schreibenden ACL-Sync.

## 2. Beispielhafte Site-Variablen – Vertrag, keine echten Werte

    bookstack_enabled: false
    bookstack_apply_approved: false
    bookstack_acl_apply_approved: false
    bookstack_legacy_migration_enabled: false
    bookstack_bridge_enabled: false
    bookstack_vmid: REQUIRED_UNALLOCATED_VM_ID
    bookstack_hostname: bookstack
    bookstack_fqdn: bookstack.example.invalid
    bookstack_release: REQUIRED_PINNED_VERSION
    bookstack_vm_storage: REQUIRED_SITE_STORAGE
    bookstack_backup_target: REQUIRED_SITE_BACKUP_PATH
    bookstack_oidc_issuer: https://idp.example.invalid
    bookstack_oidc_group_claim: groups
    bookstack_group_mapping:
      family: REQUIRED_ENVIRONMENT_GROUP
      parents: REQUIRED_ENVIRONMENT_GROUP
      children: REQUIRED_ENVIRONMENT_GROUP
    bookstack_personal_group_mapping:
      SUBJECT_A: REQUIRED_ENVIRONMENT_PERSONAL_GROUP
      SUBJECT_B: REQUIRED_ENVIRONMENT_PERSONAL_GROUP

Secrets (MariaDB Passwort, APP_KEY, OIDC Client Secret, optionale API-Tokens) gehören nicht in diese Beispieldatei oder CI-Ausgaben. Persönliche Gruppen dürfen nie aus Display-Namen konstruiert werden; stable-id, subject und environment group-mapping kontrolliert im privaten Site-Inventar verknüpfen.

## 3. Umsetzungsphasen mit Freigabegrenzen

### Phase A – Entwurfsfreigabe

- BookStack-Laufzeit, aktiver OIDC-Provider, Datenablage, Backup-Backend und zulässige Netzpfade entscheiden.
- Architektur/ACL-Vertrag und Rollenansichten mit Familienanforderungen abgleichen.
- Neue VMID aus freiem regulären Bereich auswählen und reservieren; keine 800er Alt-LXC.
- Keine Serveränderungen.

### Phase B – Proxmox, LXC und Datenhaltung

- Read-only Inventur, Identitätschecks, Preflight Kapazität, DNS, Hostkeys, Sicherungsrechte.
- Neuen unprivilegierten Debian-LXC mit eigenem Root-FS, persistentem Datenvolumen und Backup-Plan anlegen.
- Nginx, kompatibles PHP-FPM und MariaDB lokal installieren; DB mit eigenem Rechteprofil.
- BookStack fixierte Version deployen; APP_KEY beim Initialstart erzeugen und mit Sicherheitsanforderungen sichern.
- Default Admin absichern/initialen bekannten Standardzugang entfernen, kein öffentliches Registrieren/Lesen, keine echten Inhaltsdaten übernehmen.
- Read-only Diagnose und Rollback bei misslungenem Start.

### Phase C – Netzwerk, TLS, OIDC

- Backend nur von berechtigtem Reverse Proxy/Management erreichbar.
- Exakte öffentliche URL, Zertifikate, TLS und Proxy-Header kontrollieren.
- OIDC-Client mit eindeutiger Callback-URL /oidc/callback, korrektem issuer, RS256, PKCE und minimalen Scopes einrichten.
- Validieren: Subject-Stabilität; Token-Claims als Array; per-Site-Gruppendomains; OIDC_USER_TO_GROUPS + OIDC_REMOVE_FROM_GROUPS.
- Recovery über getrennten Admin-Identitätspfad und abgesicherten Betreiberkanal dokumentieren.
- Gegenprobe: OIDC-Ausfall schaltet keine öffentlichen Inhalte/unsicheren Passwort-Logins frei.

### Phase D – Wiki-Struktur und ACL

- Eltern/Kind-Konten als **gewöhnliche** Nutzer; Adminkonten separat.
- Bücher und rollenbezogene Everyone-Else-Overrides laut BOOKSTACK-ACL-CONTRACT.md.
- Fehlende oder uneindeutige persönliche OIDC-Gruppen führen zu Fail-Closed statt Default-Grant.
- Baseline-ACL via administrativer Oberfläche oder verifizierter API einrichten, anschließend Drift-Audit.
- Explizit prüfen: Zwei Eltern, zwei Kinder, Kinder A/B, Eltern persönlich P/Q, unbekanntes Konto, nicht eingeloggter Besucher.
- Kein Go-live, bevor alle ACL-01 bis ACL-20 inkl. Search/Media/API abgearbeitet sind.

### Phase E – Backup, Wiederherstellung, Updates

- Eigenen DB-Dump + alle persistierten Uploads/.env/APP_KEY in einem zeitlich konsistenten Satz erstellen.
- Geschütztes, zugängliches externes Backup-Ziel mit ausreichend freiem Platz, Retention und separaten Berechtigungen nachweisen.
- RESTORE AUF NEUEM ISOLIERTEN LXC (nicht auf Original) aus den Backup-Daten; DB, Uploads, IDP-Mapping und ACL erneut kontrollieren.
- Schwellwerte für Fullness, Backup-Alter, Backup-Fehler, Zertifikat-Ablauf, Service-Fehler und Speicherverbrauch konfigurieren.
- Einmaliges Update mit Vorher-Backup und dokumentierbarem Rollback demonstrieren; keine automatische major-Versionserhöhung.

### Phase F – Optional KI (eigenständiges Folge-PR)

- Erst nach BookStack-Go-live; default OFF.
- Read-only Wiki-Bridge als eigener optionaler Client; kein BookStack-Systemadmin-Token.
- Usergebundenen Auth-/Authorization-Nachweis, API-Tokens und rollengetrennte Caches nachweisen.
- Schreibvorschläge erst nach zusätzlicher Freigabe. Kein auto-writer und keine automatische Übernahme aus Paperless ohne Prüfung.
- Für Open WebUI/andere KI-Systeme gilt: Ein gemeinsamer RAG-Indexer mit privaten Büchern ist unzulässig.

## 4. Validierung: Testmatrix und Stop-Gates

| Gate | Konkrete Prüfung | Muss vor Go-live |
|---|---|---|
| G0 | Kein anderer LXC verändert/ersetzt; VMID eindeutig; Ziel korrekt | ja |
| G1 | BookStack/DB nach Neustart erreichbar; fest definierte Releaseversion | ja |
| G2 | Nur autorisiertes Netzwerk + HTTPS; keine Admin-/DB-Exposition | ja |
| G3 | OIDC Login A/B/P/Q; Groups, Sync, stabile sub; Fehlerfälle fail closed | ja |
| G4 | Alle ACL-01 bis ACL-20 als Negativ-/Positivtests erfolgreich | ja |
| G5 | Bilder/Anhänge/Links/Suche/Export leaken keine vertraulichen Inhalte | ja |
| G6 | Backup ist vollständig/verschlüsselungspolitisch freigegeben/extern lesbar | ja |
| G7 | Restore in isoliertem separatem LXC inkl. Rechten und APP_KEY funktioniert | ja |
| G8 | Update-/Rollback, zweiter Ansible-Lauf ohne unbeabsichtigte Changes | ja |
| G9 | AI und Paperless physisch/logisch NICHT erforderlich; optionaler Bridge-Schalter false | ja |

Bei jeder Verletzung: Release stoppen, Log ohne Geheimnisse sichern, Ursache beheben und **alle** Rechte-Regressionstests erneut ausführen.

## 5. Definition produktionsreif

Alle G0–G9 grün, Betreiberhandbuch/Recovery-Daten im geschützten Operator-Speicher verfügbar, Backup-Retention bestätigt, Sicherheitsprüfung der Rollen und öffentlich erreichbaren Wege erfolgreich. Keine Freigabe allein aufgrund erfolgreicher Installation oder einer einzelnen funktionierenden Anmeldung.

## 6. Restore/Disaster-Recovery-Ablauf (Soll)

1. Incident klassifizieren und Schreibzugriffe auf betroffene Instanz stoppen; keine destruktiven Improvisationen.
2. Gewünschten Restore-Punkt samt Manifest, APP_KEY und DB-/Upload-Konsistenz wählen und Hashes validieren.
3. Ziel-LXC **neu** und isoliert anlegen; DB/Runtime in kompatibler Version installieren.
4. DB zurückspielen, private Uploads/Anhänge/.env synchron übernehmen; APP_KEY behalten. Dateirechte reparieren.
5. Site-spezifische URL, OIDC-Client/Secrets und Proxy-Einstellungen prüfen; bei Domainänderung den BookStack-System-URL-Migrationsbefehl nur nach Backup anwenden.
6. Offline/Testpfad: revisions, attachments, images, signed-in ACL, negative ACL, Operator-Zugang und Integrität prüfen.
7. Cutover nur nach expliziter Freigabe; alte Instanz bis erfolgreicher Verifikation unverändert/archiviert halten.

Die BookStack-System-CLI gilt upstream weiterhin als Alpha; primärer Restore auf DB-Dump + Dateidaten, nicht allein auf CLI-ZIP aufbauen.

## 7. Foswiki und Migrationsrisiken

Foswiki 114 bleibt unverändert und wird unabhängig vom neuen BookStack bewertet. Nur dokumentierte historische Inhalte mit geprüften Autorenrechten/ACL und nach separater Genehmigung übernehmen. Es gibt **keinen** impliziten Anspruch, dass alte Foswiki-Gruppen in neuen BookStack-Rechten identisch sind.

## 8. Offene Implementierungsparameter (keine Benutzer-Rückfrage nötig im Entwurf)

- VMID, echte DNS-Domain, Proxy-Backend, Netzwerk/Storage, Lizenz-/Release-Pin.
- OIDC-Provider-Client, RS256/Groups, gruppenspezifische Site-Mappings, persönliche Gruppen.
- Secret-Verwahrung und Betreiberkonten, NFS-Backup-Ziel/Kapazität/Aufbewahrung, Restore-LXC.
- Konkrete Hook/API-Fähigkeiten von BookStack zur idempotenten Book-/Role-ACL-Automatisierung.
- RPO/RTO und Aufbewahrungsfristen als Betriebsvorgaben; Vorschlag RPO 24h, RTO ein Wartungsfenster, beim Implementieren mit realem Restore messen.

Diese Werte sind technische Preflight-Daten, **keine** blockierenden Produktentscheidungen und werden im jeweiligen Implementierungs-PR am echten Zielsystem festgestellt. Die produktive Freigabe bleibt gesondert.

## 9. Offizielle Quellen

- Installation: https://www.bookstackapp.com/docs/admin/installation/
- OIDC: https://www.bookstackapp.com/docs/admin/oidc-auth/
- Permission Logic: https://www.bookstackapp.com/docs/user/roles-and-permissions/
- Secure uploads: https://www.bookstackapp.com/docs/admin/upload-config/
- Backup: https://www.bookstackapp.com/docs/admin/backup-restore/
- CLI (Alpha): https://www.bookstackapp.com/docs/admin/system-cli/
- Commands/Recovery: https://www.bookstackapp.com/docs/admin/commands/
