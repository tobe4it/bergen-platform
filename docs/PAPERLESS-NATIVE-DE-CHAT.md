# Paperless 3.3.0: deutsche KI-Vorschläge und lokaler Dokumentenchat

**Status:** In Entwicklung, **nicht auf venombox aktiviert**. Dieser
Feature-Branch ist weder ein weiterer Produktiv-Apply noch ein neues
Release. Der bereits verifizierte Bergen-AI-v2-Posteingangsbetrieb aus
v0.16.0 bleibt unverändert.

## 1. Sprache und native Paperless-KI

- Die native Paperless-Anwendung besitzt die effektive Konfiguration
  `AIConfig.llm_output_language`; Zielwert ist **`de`**.
  Anwendungskonfiguration hat Vorrang vor Environment-Defaults.
- Ein weiterer explizit zu genehmigender Schritt kann `ai_enabled=true`
  konfigurieren, ohne Endpoint oder bisheriges Qwen-Modell zu ändern.
- Die integrierte KI generiert dann lokalisierte Namen und Titel,
  behält Korrespondentennamen und Klassifizierungs-IDs bei.
- Bereits angelegte englische Tags oder zuvor gespeicherte Dokumente
  werden nicht automatisch umbenannt oder neu verarbeitet.

## 2. Katalogisierungsworker: bestehende Tag-Logik unverändert

Der **bestehende** `bergen-ai-catalog.timer` verarbeitet unverändert
alle Dokumente mit `is_inbox_tag=True` und Importdatum ab 01.10.2026.
Er bleibt unabhängig von Eigentümer, Gruppe und Gruppenfreigaben.

- Der Worker verwendet `build_prompt_without_rag` für den aktuellen
  Dokumenttext und ausdrücklich sichtbare vorhandene Taxonomiekandidaten.
  Andere Dokumenttexte werden nicht als Klassifizierungskontext
  abgerufen; diese Trennung bleibt auch bei später aktiviertem
  Dokumentenchat bestehen.
- Er erhält die **originalen** Namen und IDs aus der Klassifizierung
  für die Auflösung **bestehender** Tags/Korrespondenten/Typen.
  Dadurch bleibt die automatische Zuordnung vorhandener Tags wie in
  Version 0.16.0 und respektiert weiterhin die ACL-Schutzprüfungen.
- Der zweite, lokale LLM-Aufruf mit Paperless'
  `build_localization_prompt(..., "de")` übersetzt freie Vorschläge
  für Titel, Tags und Dokumenttypen. Die auf Deutsch vorgeschlagenen
  Tag-Bezeichnungen (auch wenn **noch nicht vorhanden**) bleiben im
  `new_names`-Bereich der Vorschläge und werden in einer
  **Bergen-AI-Prüfnotiz** gespeichert.
- **Keine Liste zulässiger Tags als alleiniger Vorschlagsumfang**:
  Neue fachlich passende Tags dürfen ausdrücklich als deutsche
  *Vorschläge* erscheinen. Ein solcher Vorschlag führt niemals
  zur automatischen Erstellung des Tag-Objekts.
- Auch ein übersetzter Vorschlag verändert keine existierende
  `Tag`-Bezeichnung. Die Notiz kennzeichnet Vorschläge als nicht
  freigegeben; sie entfernt das Tag `Posteingang` nicht.
- Die technische Ausgabe an Paperless bleibt schema- und
  ID-validiert; Daten werden nicht nachträglich in Chat-Nachrichten
  oder in ein unkontrolliertes Promptformat konvertiert.

## 3. Deutscher Dokumentenchat (separater Schritt)

Der integrierte native Paperless-Chat benötigt einen durch
Dokumentenrechte gefilterten lokalen Vektorindex. Geplant ist
`llm_embedding_backend=ollama` mit
`llm_embedding_model=bge-m3:latest` auf dem vorhandenen
verifizierten privaten Ollama-Endpunkt. Dabei ist eine echte
Indexierung der Bestandsdokumente erforderlich; bloßes Setzen
der Modell-/Backend-Konfiguration ist **noch keine Aktivierung
eines benutzbaren Chats**.

Vor einer produktiven Indexierung:
1. Bestehende v2-Timer-Policy und technischen Host unverändert prüfen.
2. Effektive AI-Konfiguration und lokales Modell **rein lesend**
   auditieren; keine LLM-Inferenz, kein Indexaufbau.
3. Backup/Restore-Plan und konkrete Dokument-/Gruppenleserechte
   prüfen, insbesondere für Dokumente ohne Eigentümer.
4. Für Einstellungen: separater Fingerprint-gebundener
   Ansible-Apply mit expliziter Genehmigung.
5. Indexaufbau, Dokument-Rechtefilterung, deutsche
   Chatantwort und Negativtests mit unberechtigter
   Rolle **separat** freigeben und nachweisen.

Die native Paperless-Chat-API prüft Benutzerrechte beim
Zugriff auf Dokumente und filtert die Indexsuche nach zulässigen
IDs; die vollständige Zugriffsisolation bei Indexaufbau und
Gruppenwechsel muss dennoch vor produktiver Nutzung nachgewiesen
werden.

## 4. Rein lesender Konfigurationsaudit

Nach Aktualisierung des isolierten Worktrees auf diesen Branch:

```bash
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"
cd "$WT"
"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/manage-paperless-native-de-chat.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
```

Ohne explizite `paperless_native_de_chat_mode=apply` ist dies
**nur ein Audit**, nicht der Chat-Cutover. Für den produktiven
Betrieb fehlen derzeit noch gesonderte Abnahme der
Embedding-Indexierung und geprüfte Zugriffstests.

## 5. Aktuelle Sicherheitsprüfung vor Freischaltung des Chats

**Konfigurations-Apply vom 21.10.2026 17:38 auf venombox:** `ok=25`,
`changed=3`, `failed=0`. Der produktive Worker wurde deutsch
lokalisiert, die native Output-Language auf `de` und das
`bge-m3`-Embedding-Backend auf Ollama gesetzt, der bestehende
Fünf-Minuten-Timer wieder aktiviert. `INDEX_REBUILD=SEPARATE_APPROVAL_REQUIRED`
und `BACKFILL_OR_RECLASSIFICATION=NONE`. Der Dokumentenindex wurde mit
diesem Lauf **nicht** nachgewiesen.

**Kritischer Berechtigungsbefund aus Paperless-ngx 3.3.0:**
`has_perms_owner_aware()` gibt für `Document.owner=None`
ohne weitere Objekt-ACL-Prüfung `True` zurück.
`permitted_object_ids()` zählt die **eigentümerlosen** Dokumente
grundsätzlich zu den für einen aktiven Benutzer sichtbaren Dokumenten.
Der native Chat prüft zunächst die globale Model-Berechtigung
`documents.view_document`, anschließend greift die
Dokument-ID-Filterung auf diese Paperless-Funktionen zurück.
**Eine Gruppenfreigabe an Eltern allein ist daher bei ownerlosen
Dokumenten keine Abschottung gegenüber anderen Benutzern mit globaler
Dokumenten-Leseberechtigung.** Der tatsächliche Effekt auf bestehende
Nicht-Eltern- und Kinderkonten muss vor einem produktiven Chat geprüft
werden. Es wird keine aktuelle Datenweitergabe unterstellt.

Der genaue Test ist im neuen Read-only-Playbook enthalten:
`ansible/playbooks/audit-paperless-native-chat-access-and-index-readonly.yml`.
Das Playbook verändert weder Nutzerrechte noch den Index, erzeugt keine
Embeddings und liest weder OCR-Inhalt noch Note-Texte aus. Es gibt nur
summierte tatsächliche Zugriffszahlen und Indexstatus aus.

```bash
(
set -euo pipefail
BASE="$HOME/bergen-platform"
WT="$HOME/bergen-platform-paperless-ai-catalog"

test -z "$(git -C "$WT" status --porcelain)" || exit 1
git -C "$WT" fetch origin feat/paperless-native-german-ai-chat-20261021
git -C "$WT" switch --detach origin/feat/paperless-native-german-ai-chat-20261021
cd "$WT"

"$BASE/.venv/bin/ansible-playbook" \
  -i ansible/inventory.yml \
  -i "$BASE/ansible/inventory.local.yml" \
  ansible/playbooks/audit-paperless-native-chat-access-and-index-readonly.yml \
  --vault-id ai@prompt \
  -e "@$BASE/ansible/vars/paperless-ai-catalog.local.yml"
)
```

Entscheidend ist
`NONPARENT_VISIBLE_DOCUMENT_PAIRS` und
`CHILD_GROUP_VISIBLE_DOCUMENT_PAIRS`. Bei einem Wert über null wird
die Freischaltung des Chats gesperrt, bis ein kontrollierter
Berechtigungsentwurf und ein Negativtest vorliegen. Bei Null fehlt
immer noch der echte Session-/RAG-Berechtigungstest; die
Indexierung bleibt ein **separat freizugebender Vorgang**.
Ein vorhandenes `llmindex.db` ohne Abdeckungsnachweis bedeutet nicht,
dass alle berechtigten Dokumente bereits indiziert sind.

## 6. Referenz zur Tag-Regel

**Unverändert:** Vorhandene berechtigte Tags dürfen automatisch
ergänzt werden. Neue deutsche Tag-Vorschläge werden **ausschließlich**
in der Prüfnotiz abgelegt, nicht automatisch als Tag erzeugt.
Benutzer prüfen und entfernen anschließend manuell das
Posteingangs-Tag.

Siehe [Produktivstand v0.16.0](PAPERLESS-AI-INBOX-CATALOG-AS-OPERATED.md).
