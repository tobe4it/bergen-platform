# BookStack als eigenständiger Familienwiki-Dienst – Architekturentwurf

Status: DESIGN ONLY · 2026-10-18 · Keine Produktivfreigabe, kein Deployment.
Owner: Bergen-Platform · Service: BookStack · Keine Kopplung an Bergen-AI oder Paperless.
Referenzen: https://www.bookstackapp.com/docs/admin/installation/ · https://www.bookstackapp.com/docs/admin/oidc-auth/ · https://www.bookstackapp.com/docs/admin/upload-config/ · https://www.bookstackapp.com/docs/admin/backup-restore/

## 1. Architekturentscheidung

BookStack wird als eigenständiger, optional auswählbarer Dienst betrieben. Es ist **kein Submodul** von Paperless, Bergen-AI oder Open WebUI. Jede Integration folgt einem separat freizugebenden Schnittstellenvertrag. Keine Datenbank-, Dateisystem- oder Administrator-Credentials werden mit anderen Anwendungen geteilt.

Ziele:
- Familientaugliches Wiki mit persönlichem OIDC-Login und ausschließlich erforderlichen Rollenrechten.
- Eigener LXC auf Proxmox, eigene relationale Datenbank, lokale persistente Dateidaten, eigener Lifecycle.
- Keine Abhängigkeit von Paperless oder Bergen-AI für normalen Betrieb.
- Reproduzierbarer Ausbau über Bergen-Platform/Ansible; später als generisches optionales tobe4home-Modul geeignet.
- Versionierte Inhalte, gesicherte Medien, nachvollziehbare Änderungen und verifizierbarer Restore.

Außerhalb der ersten Ausbaustufe:
- Direkter Dokumentimport aus Paperless, Volltext-RAG, KI-Schreibautomatik, Foswiki-Migration.
- Änderung produktiver Proxmox-, DNS-, Proxy-, OIDC-, NFS- oder Wiki-Konfiguration ohne gesonderte Freigabe.

## 2. Geplantes Deployment

- Zielhost: per Site-Inventar wählbarer Proxmox-Host; im Bergen-Lab voraussichtlich venombox.
- LXC: **neu anlegen**, Debian 13, unprivilegiert, eindeutige VMID aus freier regulärer Range per Preflight feststellen. Keine Verwendung von VMID 814; 800–899 bleiben Alt-LXC-Übernahmen vorbehalten.
- Dienstname (logisch): bookstack. Keine endgültige IP, DNS-Domain, VMID oder Netzwerkkonfiguration im Repository festlegen.
- Initiale Richtwerte (vor Bereitstellung anhand Last prüfen): 2 vCPU, 2 GiB RAM, 16 GiB Systemdisk, separat erweiterbarer persistenter Datenbereich; Reserve und Monitoring vor Freigabe.
- Laufzeit: Nginx + PHP-FPM (BookStack-kompatible PHP-Version) + **lokale MariaDB**, keine Verbindung zur Paperless-Datenbank. DB ausschließlich Loopback/Unix-Socket.
- App-Root: /var/www/bookstack; Web-Root strikt /var/www/bookstack/public; Medien/Runtime darunter nach offizieller BookStack-Struktur.
- Versionspin: konkrete stabile BookStack-Version samt Quell-/Paket-Prüfsummen beim Implementierungs-PR festhalten; kein unbeaufsichtigtes Upgrade auf beweglichen release-Stand.
- Service Account und Dateirechte nach Least Privilege; .env und Secret-Dateien nur für notwendigen Prozess/Administrator lesbar.
- Firewall: Inbound Web ausschließlich aus freigegebener Reverse-Proxy-/Admin-Zone; SSH nur über etablierten PCT-vermittelten, hostkey-geprüften Managementpfad. MariaDB-Port niemals extern.
- Reverse-Proxy separat: TLS-Terminierung, feste Hostnamen aus Site-Konfig, X-Forwarded-Proto/Host nur von vertrauenswürdigem Proxy, restriktive Forwarding-/Header-Policy. Inbetriebnahme erst nach End-to-End-HTTPS-Test.
- Kein öffentliches BookStack-Registrierungsportal, kein anonymer öffentlicher Wiki-Zugriff.

### Laufzeitabhängigkeiten

BookStack ist für Darstellung/Bearbeitung von Wissen unabhängig von AI und Paperless. Der geplante Benutzer-Login setzt den vorhandenen zentralen OIDC-Anbieter voraus. Bei OIDC-Ausfall **keine** automatische Freigabe oder Fallback auf ungeschützte Anmeldung: fail closed. Administrative Wiederherstellung ausschließlich über gesicherten Betreiberkanal, mit dokumentierter Sonderfreigabe und Audit.

## 3. Inhalt und Lebenszyklus

Jeder Schutzbereich liegt in einem **eigenen Buch**, nicht bloß in einem gemeinsamen Kapitel/Shelf. Shelves sind Navigation, keine Sicherheitsschranke (Shelf-Rechte kaskadieren nicht automatisch auf Bücher).

Empfohlener Initialbestand:
- Familie: „Haus & Alltag“ (Kinder lesend) sowie „Gemeinsame Projekte“ (Kinder nach Freigabe schreibend).
- Kinder-gemeinsam: Spiele, Schule, Ausflüge und gemeinsam bearbeitbare Seiten.
- Eltern: Verträge, Finanzen, Verwaltung; Kinder keinerlei Leserecht.
- Persönlich/Kind: genau ein Buch pro Kind; nur dieses Kind darf im eigenen Buch bearbeiten; beide Eltern lesen.
- Persönlich/Eltern: genau ein Buch pro Elternteil; andere Elternteile erhalten **keinen** automatischen Zugriff.

Persönliche Kind-Bücher sind nicht für Geschwister sichtbar. Eltern erhalten Leserecht, nicht automatisch Schreib-/Löschrecht. Bei volljährigen Kindern ist das Elternleserecht durch Änderung der Policy explizit erneut zu entscheiden; keine stillschweigende unbegrenzte Fortgeltung.

## 4. Datenschutz & Hardening

- STORAGE_TYPE=local_secure_restricted. In diesem Modus wird der Zugriff auf Bilder pro Ursprungsinhalt kontrolliert. Einschränkung: Beim Kopieren von Bildinhalt in eine anders berechtigte Seite können Bilder unsichtbar bleiben; Test erforderlich.
- Datei-Anhänge liegen hinter BookStack-Autorisierung, keine öffentlich zugängliche Nebenablage.
- Public Access OFF, Registrierung OFF, Einladungen kontrolliert, sichere Session/Cookie-Konfiguration über HTTPS.
- Default Registration Role ohne Inhaltsrechte; dabei prüfen, dass die Rolle nach OIDC-Sync nicht als unerwarteter Grant wirkt.
- Keine Eltern-Konten als BookStack-Systemadministratoren für die alltägliche Nutzung. Administratoren können **alle** Bücher sehen, unabhängig von persönlicher Trennung.
- Für Pflege ausschließlich separate Admin-Identität/Break-glass mit starkem Schutz, keine gemeinsam benutzte normale Familienidentität.
- Rollen für systemweite Exporte, Benutzerauflistung, API-Tokens, Freigabelinks, Teilen, Kommentarrechte, Benutzerverwaltung und Berechtigungsverwaltung gesondert restriktiv prüfen.
- Externe Diagramm-, Font-, CDN- oder Bilddienste vermeiden bzw. vor Freigabe prüfen; keine stillen Datentransfers zu Drittanbietern.
- Keine Klartext-Inhaltsdaten in zentralen Log-/Monitoring-Systemen; Log-Retention, Backups und Löschkonzept getrennt definieren.
- Versionierung ≠ Backup ≠ rechtssichere Aufbewahrung. Aktivitätslogs/Revisionsdaten dürfen nicht unkontrolliert wachsen.

## 5. Daten, Sicherung und Wiederherstellung

Verantwortliche Daten:
- MariaDB-Schema/Inhalte/Rechtezuordnung, einschließlich Revisionen und Audit-Metadaten;
- komplette private Uploads (storage/uploads) und bei Bedarf public/uploads, themes, konfigurationsabhängige weitere Persistenz;
- .env inklusive APP_KEY, OIDC-Client-Geheimnis, sichere Betreiber-Inventare/Schlüssel separat.

Backup-Verfahren:
1. Konsistenten DB-Dump erstellen; dazu passende Uploads/Settings in einem manifestierten Backup-Lauf erfassen.
2. Auf entferntes Backup-Ziel (z.B. Synology über berechtigten NFS-Pfad) übertragen; Eigentümer/Rechte, Kapazität, Unveränderbarkeit bzw. Schutz vor Löschen vor Go-live prüfen.
3. SHA256-Manifest, Zeitstempel, Versionsstand und Restore-Anweisung pro Sicherung führen.
4. Zielwerte zur Abnahme: mindestens täglich, vor jedem Upgrade, 30 Tagessicherungen und mehrere Monatsstände **sofern Kapazität bestätigt**. Aufbewahrung und Datenklassifizierung site-spezifisch entscheiden.
5. Pro Quartal Restore in separaten isolierten LXC mit Beispieldaten, anschließend Login, Datenintegrität, Bilder, Anlagen, Versionen und ACL überprüfen. Echte vertrauliche Inhalte nicht in öffentlich erreichbare Testinstanz kopieren.
6. Recovery: gleiches APP_KEY wiederherstellen, DB + Dateidaten synchron restaurieren, URL-Konfiguration nach Bedarf kontrolliert anpassen, Sicherungen auf Vollständigkeit prüfen.

Die offizielle BookStack System CLI enthält Backup/Restore, wird aber upstream ausdrücklich noch als Alpha beschrieben. Nicht als einzige Sicherungsgrundlage einsetzen. Direkter DB-Dump plus Dateisicherung ist der Primärweg; spätere CLI-Nutzung nur ergänzend nach Restore-Test.

Kein produktiver Betrieb ohne erfolgreich validierten separaten Restore und tatsächlich verfügbaren Sicherungsplatz.

## 6. Update und Betrieb

- Versionsmanagement/Ansible-Apply nur nach explizitem Approval/Fingerprint und vorangehendem Backup.
- Rollen und Playbooks trennen: Provision LXC, BookStack Runtime, OIDC/Policy, Backup/Restore, optionale Bridge. Keine anderen Dienste in der BookStack-Rolle anfassen.
- Preflight: Ziel-Identität/VMID/DNS, DB-Größe, freie Backup-Kapazität, Snapshot/Backup-Fähigkeit, TLS-Ziel, OIDC-Metadaten/JWKS/RS256, Gruppen-Claims, Secret-Zugriff.
- Checks: HTTP intern nur aus Proxy-Zone, HTTPS extern, Dienst/MariaDB, PHP, Schreibrechte, Login, Privacy/ACL, Medienzugriff, Backup und Restore.
- Upgrade: fixierte Zielversion und Release Notes → Backup → Dry-run/Check → autorisierter Apply → DB-Migration → Funktions-/ACL-Regression → ggf. Restore-Rollback (DB-Migration nicht blind rückwärts).
- Health ohne Auth auf minimalen internen Status begrenzen; keine sensiblen Daten oder Rolleninformationen veröffentlichen.

## 7. Optionale Schnittstellen (explizit deaktiviert in Phase 1)

- OIDC ist Identitätsintegration, **keine** Freigabe für Paperless/Open WebUI.
- BookStack REST API ist gesonderte Schnittstelle. Sie darf keine API-Keys/Admin-Konten über andere Anwendungen teilen.
- Eine spätere Wiki-Bridge muss die reale Identität und BookStack-ACL pro Anfrage beweisen, die Quelle autorisieren, sensible Ergebnisse nicht global indexieren und Änderungsvorschläge vor produktivem Write freigeben.
- Keine direkten DB-Verbindungen zu Paperless oder Bergen-AI; keine Vollindexierung privater Inhalte unter einem universellen Service-Token.
- Git-/Wiki-Synchronisation, Import historischer Foswiki-Topics oder Dokumentverarbeitung jeweils als eigenständiges Folgeprojekt.

## 8. Abgrenzung Foswiki 114

Das bisherige Foswiki (LXC 114) bleibt unverändert. Erst getrennte read-only Bestandsaufnahme (Topics, letzte Änderungen, Inhalte, Zugriffe), danach Aufbewahrung/Export-Entscheidung. Keine automatische Umwidmung oder Migration nach 814.

## 9. Definition of Done

Die Abnahme ist nur erfüllt, wenn die detaillierte ACL-Matrix und die negativen Berechtigungstests aus BOOKSTACK-ACL-CONTRACT.md, das Disaster-Recovery-Gate und die Betriebsgates aus BOOKSTACK-IMPLEMENTATION-PLAN.md bestanden sind. Bis dahin: Architektur- und Implementierungsvorbereitung, **nicht deployed / nicht getestet**.
