# Bergen-AI: regulärer Paperless-Posteingang ab 01.10.2026

## Verbindlicher automatischer Ablauf

1. Paperless importiert Dokumente, erkennt Text (OCR) und führt sein
   vorhandenes klassisches Metadaten-Matching aus.
2. Der **bereits vorhandene** `bergen-ai-catalog.timer` verarbeitet im
   5-Minuten-Takt maximal ein **noch nicht journalisiertes** Dokument.
3. Die v2-Abfrage berücksichtigt `Document.added >= 2026-10-01 00:00
   Europe/Berlin` und den nativen Paperless-Posteingangstag
   (`Tag.is_inbox_tag=True`). Es gibt **keinen Filter nach owner, Gruppe,
   Freigabe oder Dokument-ID-Watermark**.
4. Für ein OCR-bereites, nicht versioniertes Dokument klassifiziert der
   lokale Ollama-Client (Qwen) ausschließlich **den aktuellen Dokumenttext**
   ohne Abruf benachbarter/fremder Dokumente. Bestehende Kategorien dürfen
   nur aus global sichtbaren, dokumenteigenen und nachweislich für Gruppen
   **dieses Dokuments** freigegebenen Objekten aufgelöst werden. Auch
   Eltern-Tags eines verschachtelten Tags müssen im gleichen Bereich
   sichtbar sein.
5. Der Worker ergänzt nur erlaubte Metadaten und eine native
   systemerzeugte Note (`Note.user=None`). Das Posteingangstag bleibt
   bestehen, bis ein Mensch es entfernt. Die manuelle KI-Oberfläche von
   Paperless bleibt unabhängig davon vorhanden.
6. Sämtliche Journal-Einträge bleiben terminal (einschließlich
   `NO_CHANGE`, `REQUIRES_REVIEW`, `PROCESSING` und `ROLLED_BACK`).
   Kein automatisches Retry, kein Überschreiben von späteren Handkorrekturen,
   keine neuen Taxonomieobjekte und keine Änderung von Eigentümern oder ACLs.

Die OCR-/Versionsschutzprüfungen sind **keine** Eigentümer- oder
Gruppenfilter: Dokumente ohne verwertbaren OCR-Text bleiben noch offen;
versionierte Dokumente benötigen gesonderte Freigabe der Mutationslogik.

## Produktivstand / Betriebsnachweis

**Am 21.10.2026 04:04 Europe/Berlin produktiv aktiviert.** Der
freigegebene Upgrade-Lauf meldete `ok=23 changed=4 failed=0`,
`TIMER=ENABLED`, `OWNER_FILTER=NONE`, `ID_WATERMARK=NOT_USED`.
Der unabhängige **08:04**-Audit bestätigte **38** relevante
Posteingangsdokumente, `READY_UNJOURNALIZED=0`, `APPLIED=33`,
`NO_CHANGE=1`, `REQUIRES_REVIEW=4` und `SYSTEM_BAI_NOTES=32`.
**Die nachstehende Upgrade-Anleitung ist für eine bereits vollzogene
einmalige Migration und darf auf dem produktiven v2-System nicht
erneut ausgeführt werden.** Für den laufenden Betrieb gilt
[das as-operated-Runbook](PAPERLESS-AI-INBOX-CATALOG-AS-OPERATED.md);
ein Git-Release ist kein erneutes Live-Deployment. Der frühere alternative Upgrade-Pfad
`upgrade-paperless-ai-inbox-catalog-all-inbox-oct2026.yml` ist
aus Sicherheitsgründen ausdrücklich gesperrt. Ein gesonderter Eltern-
oder Ein-Dokument-Pilot ist kein Bestandteil der regulären Auswahl.

### 1. Branch aktualisieren und ohne Produktivänderung prüfen

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
test -z "$(git -C "$WT" status --porcelain)" || {
  echo "STOP: uncommitted local work"; exit 1;
}
git -C "$WT" fetch origin feat/paperless-native-ai-inbox-catalog-20261018
git -C "$WT" switch --detach origin/feat/paperless-native-ai-inbox-catalog-20261018
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" -i ansible/inventory.yml \
 -i "$BASE/ansible/inventory.local.yml" \
 ansible/playbooks/upgrade-paperless-ai-all-inbox-since-20261001.yml \
 --syntax-check
)
```

### 2. Die komplette tatsächliche Posteingangsmenge rein lesend auditieren

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-ai-v2-scope-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

Relevante Nachweise sind `ALL_INBOX_ADDED_FROM_OCT1`,
`OCR_READY_UNVERSIONED`, `WAITING_OCR_OR_VERSION_REVIEW`,
`READY_UNJOURNALIZED`, `SCOPE_JOURNAL_TOTAL` und
`SCOPE_JOURNAL_STATES`. Der Audit zeigt **keine Dokument-IDs,
Eigentümer, Gruppennamen, Texte oder Notiztexte**.

### 3. Den bereits existierenden regulären Timer einmalig auf v2 umstellen

Nur ausführen, wenn die zuvor akzeptierte CT126-Sicherung verfügbar ist,
der Audit die richtige Menge bestätigt und die produktive Erweiterung
ausdrücklich freigegeben bleibt. Die folgenden Approval-Flags sind
absichtlich notwendig. Der Übergang deaktiviert den Timer nur während
des geprüften Worker-/Policy-Tauschs, verwendet weiter denselben
`bergen-ai-catalog.timer` und behält das SQLite-Verarbeitungsjournal
unverändert.

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/upgrade-paperless-ai-all-inbox-since-20261001.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml" \
  -e '{
    "paperless_ai_catalog_v2_upgrade_approved": true,
    "paperless_ai_catalog_v2_all_owners_approved": true,
    "paperless_ai_catalog_v2_history_from_october_approved": true,
    "paperless_ai_catalog_v2_regular_pipeline_approved": true,
    "paperless_ai_catalog_verified_backup": true
  }'
)
```

Der Upgrade-Lauf prüft das vorhandene v1-Policy-Format, den laufenden
Timer, den LXC und den lokal konfigurierten Modellendpunkt; danach
erfolgt eine v2-Read-only-Vorschau **vor** jedem Schreibzugriff.
Falls der Cutover scheitert, bleibt der Timer **gestoppt**
und verlangt manuelle Prüfung. Die ursprüngliche v1-Gruppenangabe
wird nur zur Identifikation der **alten** Konfiguration geprüft;
sie ist **keine** Einschränkung des v2-Dokumentbestands.

Erwartete Ergebniszeilen:

```text
TIMER=ENABLED
SELECTION=ALL_DOCUMENTS_WITH_INBOX_TAG
ADDED_FROM=2026-10-01T00:00:00_EUROPE_BERLIN
OWNER_FILTER=NONE
ID_WATERMARK=NOT_USED
NOTES=SYSTEM_ATTRIBUTED
EXISTING_JOURNAL_RECORDS=SKIPPED_NO_RETRY
DOCUMENT_INBOX_TAG=RETAINED
BATCH_SIZE=1
```

### 4. Anschließender Nachweis

Den Status via `systemctl show bergen-ai-catalog.timer -p ActiveState
-p UnitFileState` lesen; anschließend den v2-Scope-Audit erneut
ausführen und `SCOPE_JOURNAL_STATES` sowie `SYSTEM_BAI_NOTES`
beobachten. Das v1-Watermark-Audit eignet sich **nicht** für
die v2-Importdatumauswahl.

**Noch offen:** Das systemd-Journal der alten v1-Läufe zeigte bisher
keine strukturierten Worker-Frames. Ein erfolgreicher systemd-Exit
allein belegt keine Klassifizierung; die PostgreSQL-/SQLite-
Nachweise bleiben maßgeblich.
