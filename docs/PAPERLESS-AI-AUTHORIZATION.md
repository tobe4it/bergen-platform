# Bergen-AI ↔ Paperless-ngx: benutzergebundener Dokumentenzugriff

Status: **Entwurf / Sicherheitsdesign; NICHT implementiert, NICHT aktiviert** (2026-10-15).
Voraussetzung: [Paperless-Berechtigungsaudit](PAPERLESS-PERMISSIONS-AUDIT.md), 36/36
in-process DRF-Checks für vier repräsentative Dokumente am 2026-10-14 bestanden.
Das ist **keine** Freigabe der AI/RAG-Schnittstelle.

## Ausgangslage (Repository und read-only Live-Preflight)

- `bergen-ai` (LXC 110) enthält Ollama und Open WebUI.
  Relevante Dateien: `ansible/group_vars/all/bergen-ai.yml`,
  `ansible/roles/open_webui/templates/open-webui.container.j2`,
  `ansible/roles/ldap/tasks/configure.yml`.
- Open WebUI hat eigene Authentisierung und eine LDAP-Environmentdatei. Das
  allein beweist **keine** vertrauenswürdige Weitergabe einer Benutzeridentität
  an ein externes Paperless-Werkzeug.
- `bergen-paperless` (LXC 126) besitzt die Scopes
  `Privat/thomas`, `Privat/nadja`, `Eltern`, `Familie`.
  Paperless setzt bereits geprüfte Dokument-ACLs durch.
- Die Rolle setzt standardmäßig `open_webui_signup_enabled: true`; der
  Betreiber-Preflight bestätigt `ENABLE_SIGNUP=TRUE` in der laufenden
  Container-Umgebung. Das belegt die Environmentvariable, nicht die
  tatsächlich gespeicherte Registrierungspolitik.
- In der eingecheckten AI-Variablendatei stehen LDAP/389 ohne TLS und
  `ldap_validate_cert: false`. Der Live-Preflight bestätigt für den laufenden
  Open-WebUI-Prozess `LDAP_USE_TLS=FALSE` und `LDAP_VALIDATE_CERT=FALSE`.
  Das weist auf ungeschützte LDAP-Verbindungen hin, beweist aber ohne
  Netzwerk-/Protokollprüfung noch nicht den konkreten Verbindungsweg.
  Kein unverschlüsseltes LDAP als Identitätsvertrauensanker für eine
  Dokumenten-KI freigeben.

## Live-Preflight und Konfigurationsabweichung (Betreiber, 2026-10-14)

Lesendes Playbook `ansible/playbooks/audit-paperless-ai-readiness.yml`
über `venombox → pct exec 110 → podman exec open-webui`;
`ok=4 changed=0 failed=0`. Kein SSH zum DHCP-Gast benötigt.

| Indikator | Laufende Container-Umgebung |
| --- | --- |
| `WEBUI_AUTH` | TRUE |
| `ENABLE_LDAP` | TRUE |
| `ENABLE_SIGNUP` | TRUE |
| `ENABLE_PERSISTENT_CONFIG` | TRUE |
| `LDAP_USE_TLS` | FALSE |
| `LDAP_VALIDATE_CERT` | FALSE |
| Open-WebUI-Version | unbekannt (Paketmetadaten nicht gefunden) |

**Konfigurationsdrift:** Die eingecheckte Quadlet-Vorlage enthält
`ENABLE_PERSISTENT_CONFIG=false`, die laufende Container-Umgebung meldet
jedoch `TRUE`. Ursache offen: ältere Containerinstanz, nicht angewendete
Vorlage, manuelle Überschreibung oder andere Startkonfiguration. Nicht
durch ein ungeprüftes Redeploy beheben. Zuerst Container-Image,
Quadlet/Systemd-Quelle und tatsächliche Konfigurationspersistenz **lesend**
ermitteln. Bei `ENABLE_PERSISTENT_CONFIG=TRUE` können gespeicherte
Open-WebUI-Einstellungen von den Umgebungswerten abweichen.

**Preflight-PASS heißt nur:** Container und allowlist-basierte
Environmentabfrage waren erreichbar. Es ist **kein** Security-Gate-PASS
für Authentisierung, LDAP oder Paperless-RAG.

## Zielarchitektur: zentrales OIDC-SSO statt direktem LDAP-Login

**Entscheidungsvorschlag (nicht ausgerollt):** Open WebUI und Paperless als
OIDC-Clients an denselben vertrauenswürdigen Identity Provider anbinden.
LDAP bleibt Benutzerverzeichnis hinter dem IdP; Open WebUI soll
LDAP-Passwörter nicht mehr selbst prüfen. Die konkrete OIDC-Fähigkeit
der produktiven Paperless-Version und der bereits betriebenen
SSO-Komponente ist vor Änderungen zu verifizieren.

Ein Synology **SSO Server** ist als IdP grundsätzlich geeignet, wenn er
OIDC Discovery, stabile `sub`-Claims, `email`, HTTPS mit geprüftem Zertifikat,
korrekte Redirect-URIs und gewünschte MFA-Faktoren bereitstellt.
Synology Secure SignIn ist ein möglicher Faktor am SSO-Server, aber
weder LDAP noch RADIUS-Authentisierung allein ist eine OIDC-Session.

Open WebUI unterstützt OIDC über `OPENID_PROVIDER_URL`,
`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` und den Callback
`/oauth/oidc/callback`. Secrets gehören in Vault, nicht ins Repository.
`ENABLE_OAUTH_SIGNUP` ist von `ENABLE_SIGNUP` getrennt; das automatische
Anlegen von Konten muss auf die zugelassenen IdP-Benutzer beschränkt
werden. Keine unkontrollierte E-Mail-basierte Kontenzusammenführung.
Bestehende lokale/LDAP-Konten und Administratorzugriff vor der Migration
zuordnen; keine Anmeldungsmethode abschalten, bevor ein erfolgreicher
SSO-Rollbacktest vorliegt.

**Wichtig:** Gemeinsames OIDC-SSO garantiert nur dieselbe Identität
beim Login. Ein Paperless-Token aus der Open-WebUI-Session entsteht
dadurch **nicht** automatisch. Benutzergebundene API-Delegation,
Tool-Identitätsbindung und Paperless-ACLs bleiben separate Sicherheitsgates.
Insbesondere ist ein globaler Paperless-Admin-Token weiterhin verboten.

## Sicherheitsinvarianten (verbindlich)

1. **Identität:** Jede Anfrage an die Dokumentensuche besitzt eine durch den
   Server authentisierte, eindeutige Benutzeridentität. Keine vom Modell,
   Prompt, Browser oder unvalidiertem Header frei wählbaren Benutzernamen.
   LDAP-UID-/Paperless-User-Mapping explizit, eindeutig und fail-closed.
2. **Autorisierung an der Datenquelle:** Der Dokumentzugriff wird bei
   **jeder** Anfrage durch Paperless mit den Rechten des konkreten Benutzers
   geprüft. Ein technisches Dienstkonto mit globaler Dokumentleseberechtigung
   darf nicht als allgemeiner Datenkanal dienen. Niemals Admin-Token als
   Ersatz für Delegation einsetzen.
3. **Kein Umgehungspfad:** Suche, Titel, Snippets, OCR-Text, Download,
   Vorschau, Thumbnail, Zitate, Metadaten und Fehlertexte dürfen keine
   unberechtigten Informationen preisgeben. Kein direkter Ollama-Zugriff
   auf NAS-/Paperless-Dateisysteme oder eine ungeschützte globale Vektordatenbank.
4. **Isolation und Lebenszyklus:** RAG-Index, Embeddings, Chatverlauf,
   Tool-Ergebnisse und Cache sind nutzer-/ACL-gebunden; Änderungen,
   Entzug von Rechten, Löschung und Benutzerdeaktivierung müssen spätestens
   vor erneuter Auslieferung wirksam werden. Bevorzugt zunächst **ohne**
   persistente zentrale Dokumentenindexierung arbeiten.
5. **Fail closed:** Fehlende Identität, nicht eindeutiges Mapping,
   abgelaufene Berechtigung, Paperless nicht erreichbar, ungültige Antwort,
   fehlende ACL-Metadaten oder unerwartete Weiterleitung ⇒ keine Inhalte
   ausgeben. Auch keine partielle Antwort aus altem Cache.
6. **Minimale Exposition:** Nur notwendige, über TLS geschützte
   Verbindungen; kurzlebige, sicher verwahrte Credentials; kein Token
   in Prompts, Logs, Traces, Ansible-Ausgaben oder Browser-JavaScript.
   Kein Dokumentinhalt in allgemeine Modelltrainings- oder Telemetriedienste.
7. **Revisionsfähigkeit:** Technische Zugriffsnachweise enthalten
   Benutzer-ID, Zeit, Ergebnis, Dokument-ID und Korrelations-ID, aber
   keine OCR-Inhalte, Originaldateinamen oder Secrets.

## Bevorzugter Integrationspfad (erst nach Protokoll-Review implementieren)

```text
Browser
  → Open WebUI (eigene, verifizierte Session)
  → vertrauenswürdige serverseitige Tool-/Proxy-Schicht
       1. Sessionidentität serverseitig ermitteln
       2. UID eindeutig auf Paperless-Konto abbilden
       3. für diesen Benutzer authentisiert bei Paperless anfragen
       4. Ergebnisse ausschließlich aus autorisierter Paperless-Antwort übernehmen
       5. jeden nachfolgenden Dokument-/OCR-/Preview-Abruf erneut autorisieren
  → lokale Ollama-Inferenz (nur freigegebene Kontextstücke)
```

**Kritische technische Vorfrage:** Kann die eingesetzte Open-WebUI-Version
für einen Tool-Aufruf die authentisierte Benutzeridentität sicher an ein
serverseitiges Backend übergeben, und welche Paperless-Authentisierung erlaubt
tatsächlich benutzergebundene, widerrufbare API-Aufrufe? Die Schnittstellen,
Versionen und Token-Eigenschaften sind **noch nicht nachgewiesen**.
Falls eine sichere Delegation nicht möglich ist, bleibt die Integration
gesperrt. Ein Shared-Admin-Token mit nachträglicher Filterung ist keine
gleichwertige Alternative.

Initial nur **read-only, on-demand Retrieval**; keine Hintergrund-Synchronisation,
keine zentrale globale Knowledge-Collection, kein automatischer Vollimport in
Open WebUI. Der Modelloutput ist untrusted; Dokumente sind ebenfalls
untrusted und dürfen keine Tool-/Systemrechte verändern (Prompt Injection).

## Abnahmematrix vor Produktivfreigabe

| Fall | Erwartung |
| --- | --- |
| Thomas fragt nach Thomas-Privatdokument | autorisierte Treffer und Quelle |
| Nadja fragt nach Thomas-Privatdokument | **keine** Treffer, Titel, Snippets, Inhalte oder Quellen |
| Thomas fragt nach Nadja-Privatdokument | ebenfalls vollständig verweigert |
| Beide Eltern fragen nach Eltern- und Familiendokument | entsprechend den Paperless-ACLs erlaubt |
| Unberechtigter Testnutzer fragt nach Dokumenten | keine Informationen |
| Kind fragt nach privaten Elternunterlagen | vollständig verweigert, sobald echte Kinderidentität existiert |
| Identität fehlt / falscher Header / Modell fordert `user=thomas` | 401/403 ohne Daten |
| Rechte werden nach erstem Abruf entzogen | nächster Abruf, Cache und zitierte Quelle gesperrt |
| Suchtreffer wird per ID direkt heruntergeladen oder als Vorschau abgefragt | identische ACL-Durchsetzung |
| Mehrseitige Suche, Sortierung, Filter, `count`, Autocomplete | keine Informationen über unberechtigte Dokumente |
| Paperless/API/LDAP nicht erreichbar | fail-closed, keine gecachten Dokumentdaten |
| Prompt Injection im OCR-Dokument | keine Rechteerweiterung oder Datenexfiltration |
| Gleichzeitige Sessions Thomas/Nadja | kein Kontext- oder Cache-Überlauf |
| Neuimport, Rechteänderung, Benutzerlöschung | erneute Autorisierung vor jeder Ausgabe |

Die Tests müssen **über den realen Benutzerlogin und die echte AI-Tool-Kette**
laufen. `APIClient.force_authenticate` ist dafür ausdrücklich unzureichend.
Synthetische, nicht vertrauliche Testdokumente für alle vier Scopes verwenden,
zusätzlich zu einem manuellen Negativtest. Kein produktives Kindkonto nur für
den Test anlegen; bis zur Einrichtung dieser Identität bleibt die Kinderfreigabe
offen.

## Umsetzungsschritte / Gate

1. Read-only Discovery: eingesetzte Open-WebUI-/Paperless-Versionen,
   Authentisierungsfluss, LDAP-TLS, tatsächliche Signup-Einstellung,
   Reverse-Proxy-Identitätsgrenze und mögliche API-Delegation prüfen;
   keine Tokens oder Passwörter ausgeben.
2. Technische Entscheidung (mit nachgewiesenem Protokoll): sichere
   Benutzerdelegation oder **STOP**. Architektur- und Threat-Model-Review.
3. Separates Testmodul für Identity-Binding, Permission-Denials,
   Query-/Result-Filter, Download/Preview, Pagination, Cache und Revocation.
4. Nicht produktive Integration mit Testidentitäten/-dokumenten, negative
   E2E-Tests und Redaction-/Logprüfung.
5. Explizite Freigabe vor produktiver Aktivierung; erst dann
   Ansible-/Vault-Deployment und eingeschränkte Netzwerkfreigaben.

## Unabhängige Arbeit

NAS-Quarantäne/30-Tage-Retention bleibt ein eigener, deaktivierter
Lebenszyklus-Workstream. Sie darf nicht mit AI-Zugriffsrechten gekoppelt
oder durch das Mergen dieses Entwurfs aktiviert werden.

## Ansible-Zieladressierung (DHCP und Git)

`ansible/inventory.yml` enthält nur logische Hostnamen, **keine**
standortspezifischen IPv4-Adressen. Die SSH-Verbindung verwendet entweder
die Namensauflösung für `bp-controller`, `venombox` und `bergen-ai`
oder eine lokale, nicht versionierte `ansible/inventory.local.yml` mit
`ansible_host`-Overrides. Vor einem allgemeinen Ansible-Deploy die
tatsächliche Namensauflösung prüfen; das Entfernen einer IP allein
garantiert noch keine SSH-Erreichbarkeit.

`bergen-ai` bezieht seine Adresse laut IaC per DHCP; die frühere
festgeschriebene Adresse war daher kein verlässliches Betriebsmerkmal.
Das lesende Preflight-Playbook
`ansible/playbooks/audit-paperless-ai-readiness.yml` verbindet sich
ausschließlich mit dem Proxmox-Host `venombox` und führt dort
`pct exec 110 -- podman exec open-webui ...` aus. Ein SSH-Server im
AI-Gast und dessen IP-Adresse sind dafür nicht erforderlich.
Der Hostname des Gasts wird vor dem eigentlichen Test überprüft.
