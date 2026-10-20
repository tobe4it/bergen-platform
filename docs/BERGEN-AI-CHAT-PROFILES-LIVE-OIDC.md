# Bergen-AI: Vier private Chatprofile bei aktivem OIDC-Gruppensync

Stand: 20.10.2026. Auf `bergen-ai` ist die automatische Zuordnung
`ENABLE_OAUTH_GROUP_MANAGEMENT=true` produktiv aktiv. Der
Live-READ_ONLY-Audit nach Eltern-SSO-Login meldete
`ADULT_MEMBERS=1`, `FAMILY_MEMBERS=1`, `CHILD_MEMBERS=0`,
`REGISTERED_MODELS=0` und `MODEL_GRANTS=0`.
Der Kindertest und Rights-Revocation-Test bleiben getrennt offen.

## Sollprofile

| Alias-ID | Anzeigename | Ollama-Basismodell | ACL (exakt eine private Lesefreigabe) |
| --- | --- | --- | --- |
| `bergen-eltern-qwen25` | Bergen AI – Eltern | `qwen2.5:14b-instruct-q4_K_M` | Nur standortspezifische Gruppe Eltern |
| `bergen-eltern-sprachen` | Bergen AI – Sprachen | `mistral-nemo:12b` | Nur Eltern |
| `bergen-kinder-lernen` | Bergen AI – Lernbegleiter | `qwen2.5:14b-instruct-q4_K_M` | Nur Kinder |
| `bergen-kinder-sprachen` | Bergen AI – Sprachtrainer | `mistral-nemo:12b` | Nur Kinder |

Beide Kinderprofile verwenden vollständig denselben
`ansible/files/bergen_ai/prompts/learning_companion_de_v1.md` als
Systemanweisung. Enthält „Vorsagen untersagt“; ist pädagogische
Steuerung, **kein Berechtigungsmechanismus**. Elternprofile verwenden die
konstant definierte `PARENT_PROMPT` in
`manage_family_chat_profiles_v0102.py`. Nicht automatisch Paperless,
Websuche, Tools, Knowledge oder fremde Benutzer freigeben. Embedding
`bge-m3` ist kein Chatprofil.

## 1. Tokenloser READ_ONLY Preflight

Alle OIDC-/Ollama-/SQLite-Leseprüfungen erfolgen über die vorhandene
Ansible-SSH-Verwaltung; **kein Open-WebUI-Admin-API-Schlüssel notwendig**.
Er prüft aktivierten Gruppensync, die bereits vorhandene erwachsene
Mitgliedschaft, keine Eltern-/Kinderüberschneidung, genau drei konfigurierte
lokale Gruppen, die zwei Ollama-Basismodelle, bisherige Modell-Grants
und die Kinder-Lernregel, ohne persönliche Kennungen offenzulegen.

~~~bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-family-chat-live"
BR="feat/bergen-ai-family-profiles-live-oidc-20261020"
git -C "$BASE" fetch origin "$BR"
if test -e "$WT/.git"; then
  test -z "$(git -C "$WT" status --porcelain)"
  git -C "$WT" switch --detach "origin/$BR"
else
  test ! -e "$WT"
  git -C "$BASE" worktree add --detach "$WT" "origin/$BR"
fi
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-bergen-ai-family-chat-readiness-readonly.yml \
  -e "@$BASE/ansible/vars/bergen-ai-family-audit.local.yml" \
  --vault-id ai@prompt
)
~~~

Erwarteter Startbefund: `STATUS=READY_FOR_PRIVATE_PROFILES`,
`ADULT_MEMBERS=1`, `FAMILY_MEMBERS=1`, `CHILD_MEMBERS=0`,
`REQUIRED_BASE_MODELS_MISSING=0`,
`REGISTERED_MODELS=0`, `MODEL_GRANTS=0`,
`PUBLIC_MODEL_GRANTS=0`.
Fehlt ein Ollama-Modell, abbrechen und erst dessen lokal installierte
Version bestätigen. Hash-Fingerprint der geprüften Konfiguration ausgeben.

## 2. Profile tatsächlich erstellen

**Wichtig: OIDC-ENV ist nicht dasselbe wie die Modelle-REST-API.**
Schalter und OIDC konnten tokenlos per Ansible/Quadlet geändert werden.
Das Erstellen eines Workspace-Modells über die unterstützte
`POST /api/v1/models/create`-Schnittstelle benötigt dagegen eine
**authentifizierte berechtigte Open-WebUI-Sitzung**. Das letzte
Read-only-Audit kann ohne Token überprüfen; ein produktiver schreibender
REST-Apply benötigt legitime Admin-Authentifizierung. Die Anwendung soll
nicht durch direktes Schreiben in SQLite oder Fälschen eines Admin-JWT
umgangen werden.

Zwei sichere Betriebswege:

- **Ohne neue API-Key-Einstellung:** Im bereits angemeldeten Open-WebUI-
  Administratorkonto `Workspace → Models → Create`; viermal Alias-ID,
  Anzeigename, vorhandenes Basismodell, Systemanweisung und private
  Zugriffsgruppe (nur `Eltern` bzw. nur `Kinder`) konfigurieren.
  Weder `Familie` noch `Public` freigeben. Die genaue
  standortspezifische Gruppenbezeichnung wie im vorhandenen lokalen
  `bergen_ai_family_group_expected` auswählen. Nach dem Speichern
  den read-only Audit erneut ausführen, damit kein unerwarteter
  Modellbestand oder öffentlicher Grant unentdeckt bleibt.
- **Vollständig per Ansible über REST:** Der bereits vorbereitete
  `manage-bergen-ai-family-chat-profiles.yml`-Stager in diesem Branch
  akzeptiert nun aktiven OIDC-Gruppensync und vorhandene Eltern-
  Mitgliedschaften; er prüft einen stabilen privaten Gruppen-Roster
  und dessen Snapshot-Fingerprint. Sein schreibender Teil benötigt
  weiterhin ausdrücklich einen *autorisierten* Admin-Bearer
  (üblicherweise kurzlebiger API-Key oder bestehende Admin-Session)
  als verschlüsselte lokale Vault-Variable. Das Playbook erzeugt
  selbst **keinen** Schlüssel und schaltet den globalen API-Key-Schalter
  nicht um. Nicht ohne tatsächlich vorhandene sichere
  Admin-Authentifizierung ausführen. Kein direkter SQLite-Write.

Die unterstützte UI-Methode ist derzeit der unmittelbare tokenlose Weg.
Keine vorsorglichen Public-/Raw-Model-Grants vergeben, auch nicht um
Model-Not-Found-Fehler zu umgehen. Bei der Open-WebUI-Autorisierung
kann die Basismodellberechtigung zusätzlich erforderlich sein:
danach mit normalem Elternkonto positive und mit Kinderkonto negative
API-Zugriffstests durchführen.

## 3. Nachweis

Unmittelbar nach einer Anlage:
- Read-only Modelle/Grants + korrekte Besitzergruppe prüfen;
- Elternkonto: genau die zwei Elternprofile und keine Kinderprofile;
- Kinderkonto nach dessen separater OIDC-Neuanmeldung: genau die zwei
  Kinderprofile und keine Elternprofile;
- Kinderprofile zu echter Hausaufgabe testen: Hilfe mit Denkschritten
  statt fertiger Abschreibantwort;
- auch Direkt-API-Zugriff und Zugriff auf raw Ollama, Knowledge,
  fremde Chats und Paperless prüfen, nicht nur den Modellpicker.

Der Kinder-SSO-Test, API-Verweigerungstests und Gruppenentzug bei leeren
OIDC-Claims bleiben offene Freigabe-Gates. Das Aktivieren des
Gruppenschalters allein hebt diese Einschränkungen nicht auf.

**Bisheriger Bereitstellungsstand:** GitHub/CI-/Playbook-Vorbereitung,
aber noch kein produktives Chatmodell angelegt. Niemals `ok/changed`
aus dem Read-only-Preflight als Beleg für Modellanlage ausgeben.
