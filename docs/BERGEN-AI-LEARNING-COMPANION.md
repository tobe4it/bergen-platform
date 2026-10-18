# Bergen-AI Lernbegleiter: getrennte Lernerinnerung und Lerntermine (Entwurf)

Nachfolger der Entscheidungen in [Issue #98](https://github.com/tobe4it/bergen-platform/issues/98).
Voraussetzung ist die restriktive globale Ausgangskonfiguration aus
[PR #103](https://github.com/tobe4it/bergen-platform/pull/103).
**Diese Dokumentation und ihr Playbook ändern produktiv keine einzige Berechtigung.**

## Angestrebtes Verhalten

Die KI unterstützt eigenständiges Lernen. Bei echten Hausaufgaben fragt sie
nach vorhandenen Versuchen, bietet kurze Hinweise und Beispiele zu
**vergleichbaren Aufgaben**, stellt Verständnisfragen und prüft eigene
Antworten. Sie verfasst keine abschreibbaren fertigen Hausaufgaben oder
Musterlösungen für einzureichende Aufgaben. Für von der KI selbst erzeugte
Übungsbeispiele sind vollständige Lösungswege zulässig.

Es gibt zwei **getrennte, nutzerbezogene Datentypen**:

- **Lernfortschritt / Memory**: Fach, Thema, demonstrierte Fähigkeit,
  offener Übungsbedarf, ungefähres Übungsdatum. Nicht die vollständigen
  Schulaufgaben oder Bewertungen der Persönlichkeit.
- **Lerntermin / Kalenderereignis**: Datum, Uhrzeit, Zeitzone, optional
  Fach/Thema, optionaler Erinnerungszeitpunkt. Keine erfundenen
  Termine. Elternfreigabe für gemeinsame Kalender und externe Zustellung.

Die Systeme sollen Kinder zu eigenständigen kurzen Wiederholungen einladen,
nicht beschämen, Druck aufbauen oder Chatabhängigkeit fördern. Für jüngere
Kinder sind einfachere Fragen und kurze Lerneinheiten vorzusehen.

Die versionierte Verhaltensvorlage liegt unter
`ansible/files/bergen_ai/prompts/learning_companion_de_v1.md`.
**Sie ist noch nicht in einen produktiven Open-WebUI-Modell-Datensatz
übernommen** und begründet **keine** technische Gewähr gegen Umgehung
oder fertig gelöste Aufgaben. Ein separates Modellprofil mit
System-Prompt plus negativen Tests muss erst eingeführt werden.

## Rechtemodell: keine Hierarchie, sondern additive Gruppen

Open WebUI 0.10.2 kombiniert die **globalen Standardberechtigungen und alle
expliziten Gruppenmitgliedschaften durch logisches ODER**. Eine Gruppe
`Kinder` kann ein `true` aus `Familie` oder global nicht verbieten.
Die Gruppen sind nicht ineinander verschachtelt.

| Fähigkeit | Globale Basis (Soll) | Familie (Soll) | Eltern (zusätzlich) | Kinder (zusätzlich) |
| --- | --- | --- | --- | --- |
| Persönliche KI-Unterhaltung | Grundfunktion | – | – | – |
| Eigener Lernfortschritt / `features.memories` | OFF | **ON** | – | – |
| Eigener Kalender / `features.calendar` | OFF | **ON** | – | – |
| Allgemeine KI-Automationen / `features.automations` | OFF | OFF | Optional, erst nach Test | **OFF** |
| Websuche / `features.web_search` | OFF | OFF | Optional | OFF |
| Datei- und Web-Uploads | OFF | OFF | Nach Datenschutzprüfung | OFF |
| Bildgenerierung, Code-Interpreter | OFF | OFF | Optional | OFF |
| Öffentliche Freigaben und Chat-Links | OFF | OFF | Optional nach Freigabeprüfung | OFF |
| API-Schlüssel, freie Toolserver, Webhooks | OFF | OFF | Nur gesondert geprüft | OFF |

**Das ist ein Zielzustand, kein behaupteter Istzustand.**
Insbesondere wurden in PR #103 nur **vier** globale Rechte deaktiviert:
`features.web_search`, `features.image_generation`,
`features.code_interpreter`, `chat.file_upload`.
Weitere global hinterlegte Rechte (u. a. Memories, Kalender, Chat-Share,
Web-Uploads und öffentliche Notizen/Tools) müssen vorher geprüft werden.
Erst danach kann ein separater, idempotenter und ausdrücklich freigegebener
Ansible-Apply die gemeinsame Basis und Familiengruppen einrichten.

Eine freigegebene Memory-Funktion muss **pro angemeldetem Kind** geführt
werden; weder in `Familie` noch in `Kinder` werden gemeinsame
Lernfortschrittsdatensätze gespeichert. Memory-Löschung, Zugriff auf
alte Erinnerungen, Berechtigungswiderruf und Trennung der
`user-memory-{user.id}`-Vektorsammlungen müssen tatsächlich getestet werden.
Die technische Speichertrennung ersetzt nicht die Prüfung anderer
Zugriffswege und administrativer Vollmachten.

## Reminder-Architektur – getrennt von freien KI-Automationen

Open WebUI v0.10.2 besitzt:
- `features.calendar` + `calendar.enable`: persönliche Kalender und
  Kalenderereignisse; geteilte Kalender benötigen geprüfte ACLs.
- `features.automations` + `automations.enable`: frei geplante
  KI-Workflows, unter Umständen einschließlich Tools. Kinder sollen diese
  allgemeine Funktion **nicht** benötigen.
- Ein Scheduler in `backend/open_webui/utils/automations.py` prüft
  bevorstehende Kalenderereignisse und erzeugt benutzerbezogene
  Socket-Ereignisse. Optional existiert eine Webhook-Zustellung, die
  nur nach separater Sicherheits- und Datenschutzprüfung nutzbar wäre.

Ein Kalendereintrag oder Socket-Ereignis ist **keine belegte mobile
Push-Nachricht**, wenn iPad/iPhone bzw. die Weboberfläche geschlossen sind.
Für echte Terminerinnerungen muss der Zustellkanal, die Erreichbarkeit,
Zeitzonen- und Sommerzeitbehandlung und die Zustellung bei inaktivem Chat
per E2E-Test nachgewiesen werden. Ein möglicher begrenzter, betreuter
Reminder-Zusteller gehört als **gesondertes** Ansible-Modul mit eigener
ACL-/Token-/Webhook-Freigabe in den weiteren Entwicklungsprozess;
keine allgemeinen Automationen für Kinder freischalten.

Keine Erinnerung darf ohne nachweislich bestätigten Termin als erstellt
ausgegeben werden. Vermeiden von Doppelbenachrichtigungen und ein
nachvollziehbarer Lösch-/Widerrufsmechanismus sind Release-Gates.

## Nur lesende Ansible-Vorprüfung

Das Playbook `ansible/playbooks/audit-bergen-ai-learning-companion-readonly.yml`
nutzt das bestehende, ignorierte lokale File
`ansible/vars/bergen-ai-family-audit.local.yml`. Es benötigt **keinen
Admin-API-Token**, führt keine ORM- oder SQL-Schreiboperationen aus und
liest keine Nutzerdaten, Memory-Inhalte oder Termine.

Voraussetzungen: einzelner genehmigter Host `bergen-ai`, laufende
Open-WebUI-Version `0.10.2`, persistente SQLite-Konfiguration und
genau drei vorhandene private Gruppen ohne Mitgliedschaften. Abweichungen
brechen ab. Es werden ausschließlich feste Flags/Kategorien und
hypothetisch addierte Gruppenrechte ausgegeben, **keine** Namen,
Gruppen-/Nutzer-IDs, Inhalte oder Geheimnisse.

Im bereits bestehenden PR-Worktree ist ein **eigener** Worktree
anzulegen, damit der laufende PR #103 nicht beeinflusst wird:

```bash
cd "$HOME/bergen-platform-ai-family-audit"
git fetch origin feat/bergen-ai-learning-companion-20261018
git worktree add --detach "$HOME/bergen-platform-ai-learning-companion" FETCH_HEAD
cp -p ansible/vars/bergen-ai-family-audit.local.yml \
  "$HOME/bergen-platform-ai-learning-companion/ansible/vars/bergen-ai-family-audit.local.yml"
cd "$HOME/bergen-platform-ai-learning-companion"

BASE="$HOME/bergen-platform"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-learning-companion-readonly.yml \
  --vault-id ai@prompt \
  -e @ansible/vars/bergen-ai-family-audit.local.yml
```

Die meisten Zeilen benennen den *persistierten Istzustand*. Ausgaben
`CHILD_IF_ASSIGNED_*` simulieren nur die additive Rechtesemantik unter
der **künftigen Annahme**, dass das betreffende Kind Mitglied von
`Familie` und `Kinder` wäre. Sie bedeuten **nicht**, dass das Kind
aktuell Mitglied ist, dass APIs tatsächlich geschützt sind oder dass
Reminders ausgelöst werden. `MEMORY_ISOLATION_E2E`,
`REMINDER_DELIVERY_E2E`, `HOMEWORK_BEHAVIOR_E2E` und
`RESOURCE_ACL_SEPARATION_E2E` bleiben ausdrücklich
`NOT_PROVEN`.

## Release-Gates

1. CI-Fixtures und Ansible-Syntaxprüfung für den Read-only-Audit.
2. Produktiver Read-only-Audit des persistierten Istzustands
   einschließlich globaler Memory-/Kalender-/Automationsrechte.
3. Eigenständiger Ansible-PR für sicherheitsgeprüften globalen
   Minimalstandard und explizite Familienrechte, mit Backup,
   exaktem Soll-/Ist-Fingerprint, idempotentem Apply und Rollback.
4. Genehmigtes und getestetes kinderfreundliches Modellprofil mit
   versioniertem Prompt (keine Behauptung technischer Hausaufgabensperre).
5. Isolierte Tests als Kind 1 / Kind 2 / Eltern, einschließlich
   Memory-Schreiben, Abruf, Korrektur, Löschung, negatives Cross-User-Lesen,
   API-Negativtests und zuverlässig ausgeführtem Rechteentzug.
6. Kalendertermin erstellen, wiederkehrenden Termin und Zeitzone prüfen,
   Reminder bei geschlossenem Chat auslösen und tatsächlichen
   vereinbarten Zustellweg messen; nicht nur Socket-Event simulieren.
7. Kein automatisches OIDC-Gruppenmanagement, keine neuen Admin-/API-Tokens,
   keine unkontrollierten externen Webhooks und keine Kindergruppenmitglieder
   vor den Sicherheitsprüfungen.
