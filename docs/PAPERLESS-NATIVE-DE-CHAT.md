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

## 5. Referenz zur Tag-Regel

**Unverändert:** Vorhandene berechtigte Tags dürfen automatisch
ergänzt werden. Neue deutsche Tag-Vorschläge werden **ausschließlich**
in der Prüfnotiz abgelegt, nicht automatisch als Tag erzeugt.
Benutzer prüfen und entfernen anschließend manuell das
Posteingangs-Tag.

Siehe [Produktivstand v0.16.0](PAPERLESS-AI-INBOX-CATALOG-AS-OPERATED.md).
