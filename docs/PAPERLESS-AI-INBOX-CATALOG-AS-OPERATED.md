# Bergen Paperless-AI: Produktivbetrieb v2 (Stand 21.10.2026)

**Release:** Bergen Platform v0.16.0 · **Umgebung:** bestehender Proxmox-Host
`venombox`, unprivilegierter Paperless-Gast CT126, Paperless-ngx **3.3.0**.
Dieser Text beschreibt den **nachgewiesenen produktiven Iststand**. Quellcode
und Git-Release bewirken selbst weder ein neues Apply noch ein KI-Retry.
Die konkrete Abnahme erfolgte bereits durch den Betreiber am 21.10.2026.

## 1. Gültiger Prozess

1. Der reguläre Paperless-Import läuft weiter über die bestehende Infrastruktur.
   Paperless erledigt OCR und seine bisherigen Metadaten-/Matching-Schritte.
2. Der **bestehende** `bergen-ai-catalog.timer` auf `venombox` startet seinen
   `bergen-ai-catalog.service` alle fünf Minuten. Pro regulärem Lauf wird
   höchstens **ein** noch nicht journalisiertes geeignetes Dokument ausgewählt.
3. Maßgeblich sind ausschließlich:
   - das **native** Paperless-Posteingangstag: `Tag.is_inbox_tag=True`;
   - `Document.added >= 2026-10-01T00:00:00+02:00`, also der **Import** ab
     dem 01.10.2026 00:00 Europe/Berlin (nicht das Dokumentdatum `created`).
   Es gibt **keinen** Filter nach Eigentümer, Gruppenmitgliedschaft,
   Gruppenfreigaben, Administratorrolle oder Dokument-ID-Watermark.
4. Ein Dokument muss aktuell mindestens 30 nichtleere OCR-Zeichen haben und
   darf nicht Teil einer separat ungeprüften Versionskette sein. Dies sind
   Verarbeitungs-Voraussetzungen, **keine** Einschränkungen nach Besitzer.
5. Die Metadatenklassifizierung läuft lokal über den bereits eingerichteten
   Paperless/Ollama-Zugriff (Qwen `qwen2.5:14b-instruct-q4_K_M`).
   V2 baut den KI-Prompt **ohne Abruf ähnlicher fremder Dokumenttexte**
   (`build_prompt_without_rag`). Das verhindert die native
   `user=None`-Kontextsuche, die ansonsten andere geschützte Texte
   heranziehen könnte. Bestehende Taxonomieeinträge werden anhand globaler,
   dokumenteigener oder ausdrücklich mit den am Dokument berechtigten
   Gruppen geteilter Objekte zugeordnet und vor dem Schreiben erneut geprüft.
   Auch implizit hinzugefügte übergeordnete Tags müssen sichtbar sein.
6. Zulässig sind ausschließlich der vorsichtige Austausch eines
   dateinamenbasierten Importtitels, Ergänzung bislang leerer Felder
   Korrespondent/Dokumenttyp und additive bereits bestehende Tags.
   Kein automatisches Löschen des Posteingangstags, keine neuen Kategorien,
   keine Änderung von Eigentümer, Dokument-/Gruppenrechten, Archiv- oder
   Originaldateien, Speicherpfaden und Daten.
7. Zusätzlich legt v2 eine native Paperless-Notiz mit
   `Note.user=None` an. Diese Notiz kennzeichnet KI-Vorschläge zur
   **manuellen** Freigabe. Das Posteingangstag entfernt später ein Mensch.
   Der Paperless-eigene Klassifikator kann nach manueller Freigabe
   weiterhin aus den klassischen Metadaten lernen; ein zusätzliches
   automatisches LLM-Training ist **nicht** nachgewiesen.

## 2. Auditierbarer Produktivnachweis

Der Betreiber führte am **21.10.2026** den v2-Umfangsaudit und das freigegebene
v1→v2-Upgrade auf dem vorhandenen `bp-controller` aus.

| Vorgang (Europe/Berlin) | Ergebnis |
| --- | --- |
| 04:02, Read-only vor Upgrade | `AUDIT=READ_ONLY`, `STATUS=INSPECTED`, `ok=9 changed=0 failed=0` |
| Dokumentbestand vor Upgrade | `ALL_INBOX_ADDED_FROM_OCT1=38`, `OCR_READY_UNVERSIONED=38` |
| Ausgangs-Journal | `SCOPE_JOURNAL_TOTAL=6`: `APPLIED=2`, `NO_CHANGE=0`, `REQUIRES_REVIEW=4` |
| Vorher noch nicht verarbeitet | `READY_UNJOURNALIZED=32` |
| 04:04, kontrollierter v2-Cutover | `ok=23 changed=4 unreachable=0 failed=0` |
| Nachweis installierter Timer-Policy | `TIMER=ENABLED`, `SELECTION=ALL_DOCUMENTS_WITH_INBOX_TAG`, `ADDED_FROM=2026-10-01T00:00:00_EUROPE_BERLIN`, `OWNER_FILTER=NONE`, `ID_WATERMARK=NOT_USED` |
| 08:04, unabhängiger Read-only-Audit | `ok=9 changed=0 failed=0` |
| Dokumentbestand nach Upgrade | `ALL_INBOX_ADDED_FROM_OCT1=38`, `OCR_READY_UNVERSIONED=38`, `WAITING_OCR_OR_VERSION_REVIEW=0` |
| Abschluss-Journal | `SCOPE_JOURNAL_TOTAL=38`: `APPLIED=33`, `NO_CHANGE=1`, `REQUIRES_REVIEW=4`, `PROCESSING=0`, `ROLLED_BACK=0` |
| Nicht journalisierte Dokumente | `READY_UNJOURNALIZED=0` |
| Systemseitig zugeordnete v2-Notizen | `SYSTEM_BAI_NOTES=32` |

**Interpretation:** Zwischen den beiden Audits wurden sämtliche **32**
vorher noch nicht journalisierten, geeigneten Posteingangsdokumente
verarbeitet; der Zustandsvergleich ergibt **31 zusätzliche `APPLIED`**
und **1 zusätzliches `NO_CHANGE`**, **keinen neuen Review-Fall**.
Über den gesamten Bestand weisen 34 Dokumente einen abgeschlossenen
Erfolgsstatus auf und 4 einen alten Review-Status. `APPLIED` ist ein
Journalzustand und **keine** Qualitätsprüfung sämtlicher Metadaten.

Die vollständigen Operator-Ausgaben sind der Nachweis; diese
Dokumentation enthält **nur aggregierte Zahlen**, keine IDs, OCR-Texte,
Dateinamen, Gruppenlisten, Endpunkte, API-Schlüssel oder Notiztexte.

## 3. Bestehende Installation und Wiederholbarkeit

- Quell-Branch vor Release: `feat/paperless-native-ai-inbox-catalog-20261018`.
- Verwendete Upgrade-Quelle:
  `ansible/playbooks/upgrade-paperless-ai-all-inbox-since-20261001.yml`.
- Bestehender systemd-Timer und Dienst:
  `bergen-ai-catalog.timer`, `bergen-ai-catalog.service`.
- Installierte, rootgeschützte Runtime-Artefakte auf `venombox`:
  `/etc/bergen-platform/paperless-ai/catalog-policy.json`,
  `bergen_ai_catalog_policy.py`, `bergen_ai_catalog_runner.py`.
- Der vorhandene Launcher `/usr/local/libexec/bergen-ai-catalog-run`
  startet den Worker innerhalb des Paperless-Podman-Containers.
- Das **vorhandene** private SQLite-Journal unter
  `/usr/src/paperless/data/.bergen-ai-catalog-v1/catalog.sqlite3`
  bleibt erhalten; der Verzeichnisname `v1` ist **historisch** und
  bedeutet keine Rückkehr zur alten Dokumentauswahl.
- Jeder dokumentbezogene Journalzustand bleibt für den Timer terminal:
  `APPLIED`, `NO_CHANGE`, `REQUIRES_REVIEW`, `PROCESSING`,
  `ROLLED_BACK`. Die Verarbeitung bereits journalisierter IDs wird
  **nicht** automatisch wiederholt. Schreibkonflikte werden fail-closed
  behandelt. Der Timer ist weiter aktiv; ein bereits verarbeiteter
  Posteingang wird nicht jede Runde neu klassifiziert.

**Ein produktiver zweiter Upgrade-Apply mit `changed=0` wurde nicht
nachgewiesen.** Der v1→v2-Cutover prüft die alte Konfiguration und ist
nicht als automatisch erneut auszuführender v2→v2-Befehl freigegeben.
Die **zeitgesteuerte Dokumentverarbeitung** ist durch das Journal
nachgewiesen, nicht die Idempotenz des *Upgrade-Playbooks*.

## 4. Sicherer laufender Audit

Auf dem bestehenden `bp-controller`, aus einem auf den Release-Commit
aktualisierten Worktree, ohne Freigabevariablen für Änderungen:

```bash
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-v2-scope-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
```

Erwartet: `AUDIT=READ_ONLY`, `STATUS=INSPECTED`,
`MODEL_INFERENCE=NO`, `DOCUMENTS_CHANGED=NO`,
`CHANGED=False`. Kontrolliere `READY_UNJOURNALIZED`,
`SCOPE_JOURNAL_STATES` und `SYSTEM_BAI_NOTES`. Bei neuen Imports
darf `READY_UNJOURNALIZED` vor dem nächsten regulären Lauf kurz
wieder größer null sein. Das Audit enthält keinen KI-Aufruf.

Zur gesonderten reinen Timerstatusprüfung:
`systemctl show bergen-ai-catalog.timer -p ActiveState -p UnitFileState`
auf `venombox`; ein erfolgreicher systemd-Service-Exit alleine
belegt **keine** erfolgreiche KI-Klassifizierung.

## 5. Release-Grenzen / offene Nachweise

1. **Vier alte `REQUIRES_REVIEW`-Dokumente:** weiterhin gesperrt,
   keine automatische Wiederholung oder Löschung von Journalzeilen.
   Separate Fehler- und Metadatenprüfung erforderlich.
2. **Qualität:** Keine vollständige manuelle Abnahme der 32 neuen
   Notizen/Titel/Korrespondenten/Typen/Tags protokolliert. Das
   Journal bestätigt den technischen Abschluss, nicht inhaltliche
   Richtigkeit oder die Sichtbarkeit jeder Notiz im Nutzer-UI.
3. **Logging:** Die alte v1-systemd-Ausgabe enthielt keine
   `BERGEN_PAPERLESS_AI_CATALOG_V1:`-Frames; eine Korrektur und ein
   erneuter Nachweis des neuen strukturierten Loggings sind **nicht**
   dokumentiert. Ein separates Observability-Arbeitspaket bleibt offen.
4. **Backup:** Der Operator setzte beim Upgrade den geschützten
   Backup-Bestätigungsparameter. Ein unabhängiger Wiederherstellungstest
   aus diesem Protokoll liegt nicht vor.
5. **Sicherheit:** Die abgeschlossene Katalogisierung ist **kein**
   Beleg für eine vollständig negativ getestete Ollama-Port-11434-
   Expositionskontrolle; diese ist gesondert zu auditieren.
6. **Abgrenzung:** Kein automatisches Entfernen des Inbox-Tags, keine
   AI-Vorschlagsfreigabe durch die KI, keine sichere Originaldatei-
   Löschung, kein Freischalten von zurückgehaltenen alten Dokumenten.
   Der ältere alternative Cutover
   `upgrade-paperless-ai-inbox-catalog-all-inbox-oct2026.yml`
   ist wegen seines unbeschränkten `user=None`-RAG-Pfads
   **deaktiviert** und darf nicht angewendet werden.

**Abnahmegrad:** Produktive Funktion der eigentümer-/gruppenunabhängigen
Bergen-AI-Posteingangskatalogisierung bis zum 21.10.2026 **technisch
verifiziert**. Nacharbeiten werden separat geführt und sind **keine**
Voraussetzung, um die bereits nachgewiesene Funktion zu versionieren.

Referenzen: [v2-Umstellung](PAPERLESS-AI-ALL-INBOX-V2-DEPLOY.md),
[ursprüngliches Entwicklungsprotokoll](PAPERLESS-AI-INBOX-CATALOG.md),
[CHANGELOG](CHANGELOG.md) und [Release Notes](releases/v0.16.0.md).
