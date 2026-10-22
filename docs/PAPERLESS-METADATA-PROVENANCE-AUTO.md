# Paperless-ngx 3.3.0 – native Metadaten-Synchronisierung mit Rechteherkunft

Stand: 22.10.2026, Feature-Branch **staged only**. Weder neue
Datenbanktabelle noch Timer wurde bereits produktiv angelegt/aktiviert.

## Nachgewiesener Bestand

- 60 Dokumente, 3 aktive menschliche Mitglieder in
  \`Familie@bergen.intern\`.
- 38 bestehende Tags für alle sichtbar.
- 8 Dokumenttypen, 13 Korrespondenten; bestehende Dokument-bedingte
  Rechte nach dem unabhängigen Folgeaudit vollständig: je 0 Lücken.
- Thomas' 9 private Dokumente weiterhin nicht für Nadja sichtbar.
- Kein Kind sieht Dokumente der Gruppe Eltern oder Thomas' private
  Dokumente.

Die **38 bestehenden** Tag-Objektberechtigungen und die **21 bestehenden**
per-user Dokumenttyp-/Korrespondentenberechtigungen bleiben absichtlich
außerhalb der Eigentümerschaft des neuen Automaten. Sie wurden von anderen
genehmigten Abläufen eingerichtet und dürfen vom neuen Worker **niemals**
ohne eigene gesonderte Migration entzogen werden.

## Dauerhafte Regeln

- **Tags:** Jede bereits vorhandene und neue Tag-ID besitzt das native
  \`view_tag\`-Objektrecht für \`Familie@bergen.intern\`. Die Namen können
  dabei auch privat verwendete Tags enthalten, jedoch niemals die
  dazugehörigen privaten Dokumentinhalte.
- **Dokumenttypen/Korrespondenten:** Ein aktives Familienmitglied erhält
  nur dann ein fehlendes \`view_documenttype\` beziehungsweise
  \`view_correspondent\`-Objektrecht, wenn es schon ein Dokument mit der
  jeweiligen Zuordnung lesen darf.
- **Automatischer Entzug:** Nur **vom neuen Worker tatsächlich hinzugefügte**
  Rechte werden in der eigenen Ledger-Tabelle verzeichnet. Entfällt die
  letzte sichtbare Dokumentverknüpfung oder die Familienmitgliedschaft,
  darf ausschließlich der exakt protokollierte Grant wieder entfernt werden.
  Vorbestehende und außerhalb des Workers manuell vergebene Rechte werden
  niemals übernommen oder entzogen.
- **Wichtig:** Ein Recht, das ein Mensch nachträglich durch dieselbe
  native Guardian-Zeile erneut bestätigt, ist technisch nicht von
  der ursprünglichen vom Worker angelegten Zeile unterscheidbar. Die
  Verfahrensregel lautet deshalb: Ein vom Worker verwaltetes Recht nicht
  zusätzlich manuell mit derselben Ziel-ID „übernehmen“; statt dessen
  das Recht zuerst aus der Automatik ausnehmen und dann separat migrieren.
  Ohne eine solche organisatorische Regel ist eine *absolut sichere*
  Erkennung einer nachträglichen manuellen Übernahme unmöglich.
- **Keine Dokument-ACLs oder Dokumentänderungen.** Durch Metadatenrechte
  entstehen weder Dokument-Leserechte noch Bearbeitungsrechte.

## Transaktionale Ledger-Datenhaltung

Die Tabelle \`public.bergen_platform_paperless_acl_grants_v1\` enthält nur:
\`subject_kind\`, \`subject_id\`, \`permission_id\`, \`object_pk\`. Die
vier Spalten bilden gemeinsam den Primärschlüssel. Es sind keine
Dokumentinhalte, OCR, Dateinamen, Namen oder Zugangsdaten enthalten.
Die Tabelle wird **erst bei separat genehmigtem Apply** angelegt,
und zwar innerhalb derselben PostgreSQL-Transaktion wie die
neu erzeugten Native-Guardian-Rechte. Das Skript prüft ihren
festen Eigentümer-Kommentar, Datenbanktyp und Schema.

Die Änderung verwendet \`SERIALIZABLE\` und eine transaktionale
Advisory-Lock-Sperre sowie vollständige Soll-/Ist-Vergleiche. Fehlende
Native-Grants und bestehende Ledger-Einträge werden idempotent
zusammengeführt. Der selbstverwaltete ACL-Satz und die Ledger-Zeilen
müssen vor Commit exakt übereinstimmen.

Snapshot und Negativprüfungen umfassen: Dokument-Eigentümer und
Metadatenzuordnung, Dokument-Gruppen/User-ACLs und effektive
\`view/change/delete_document\`-Rechte, Tag-Zuordnungen,
Metadaten-Eigentümer, nicht zum Worker gehörige Rechte,
Gruppenmitgliedschaften, globales Gruppen-/Benutzer-Rechtesystem,
Eltern-Sperren und private Thomas-/Nadja-Grenze.

Fehlgeschlagene Bedingungen verursachen \`BLOCKED\`, keine
Teilfreigabe. Rücknahme von DB-Schreiboperationen läuft über
\`transaction.atomic\`. Für Browser-Änderungen/Fehler ist kein
Nginx-Eingriff enthalten.

## Bereitgestellte Dateien

- \`ansible/files/paperless/reconcile_metadata_with_provenance.py\`
- \`ansible/playbooks/manage-paperless-metadata-provenance.yml\`
  (**read-only Default**, separat freigegebener Einmal-Apply).
- \`ansible/files/paperless/bergen_metadata_auto_runner.py\`
- \`ansible/files/paperless/bergen-paperless-metadata.service\`
- \`ansible/files/paperless/bergen-paperless-metadata.timer\`
- \`ansible/playbooks/activate-paperless-metadata-timer.yml\`
  (**niemals** bei bloßem Audit aufgerufen).
- \`tests/test_paperless_metadata_provenance_reconciler.py\`

## Phase A: Nur Tests und Read-only-Audit

Die Live-Prüfung muss vor jedem Apply das Ledger als \`ABSENT\` oder
\`VALID\` melden und die für den aktuellen Stand **tatsächlich
festgestellten** Zähler angeben. Nicht aus alten Logs übernehmen.

\`\`\`bash
(
  set -euo pipefail
  BASE="$HOME/bergen-platform"
  WT="$HOME/bergen-platform-metadata-auto"
  BRANCH=feat/paperless-metadata-reconciler-provenance-20261022

  git -C "$BASE" fetch origin "$BRANCH"
  PIN="$(git -C "$BASE" rev-parse FETCH_HEAD)"
  if ! test -d "$WT"; then
    git -C "$BASE" worktree add --detach "$WT" "$PIN"
  fi
  cd "$WT"
  test -z "$(git status --porcelain)"
  git switch --detach "$PIN"

  "$BASE/.venv/bin/python" -m unittest discover -s tests \\
    -p 'test_paperless_metadata_provenance_reconciler.py' -v

  "$BASE/.venv/bin/ansible-playbook" \\
    -i ansible/inventory.yml \\
    -i "$BASE/ansible/inventory.local.yml" \\
    ansible/playbooks/manage-paperless-metadata-provenance.yml \\
    --vault-id ai@prompt
)
\`\`\`

Erwarteter unveränderter Altbestand (vor neuem Tag/Import):
\`DOCUMENTS=60\`, \`USERS=3\`, \`TAGS=38\`,
\`TYPE_GAPS=0\`, \`CORR_GAPS=0\`, \`TAG_GAPS=0\`,
\`MANAGED_REVOCATIONS=0\`, \`THOMAS_PRIVATE=9\`,
\`LEDGER=ABSENT\`, \`CHANGED=False\`. Diese Werte sind nur
historische Erwartungswerte; abweichende Live-Zähler neu prüfen.

## Phase B: Separat genehmigte Ledger-Initialisierung

Dieser Lauf ist eine **Datenbankänderung**, selbst wenn alle
Berechtigungslücken bereits null sind. Er erfordert die aktuelle
NFS-Backup-Prüfung (< 48 Stunden), \`paperless_taxonomy_apply_approved=true\`,
\`paperless_taxonomy_database_ledger_approved=true\`,
\`paperless_ai_catalog_verified_backup=true\` und die acht exakt
aus Phase A abgelesenen Live-Zähler. Nach Apply: erneuter
Read-only-Audit und Datenschutztest.

Eine Beispielkommandozeile für den historischen Zustand 60/3/38/0/0/0/0/9
ist bewusst **nicht** als pauschale Freigabe dokumentiert. Die Zahlen
müssen erst in Phase A erneut bestätigt werden.

## Phase C: Separat genehmigte Timeraktivierung

\`activate-paperless-metadata-timer.yml\` ist von Phase A/B komplett
getrennt. Aktivierung benötigt *eigenständige* Zustimmung
\`paperless_metadata_timer_activate=true\`,
\`paperless_metadata_timer_approved=true\` und einen unabhängig
bestätigten \`paperless_metadata_provenance_bootstrap_verified=true\`.

- Nichts wird bei bloßem Checkout oder Audit installiert.
- Fixiertes, root-eigenes Policy-Skript und SHA256-Pin, kein API-Key.
- Eigener \`bergen-paperless-metadata.timer\`, stündlicher Durchlauf,
  bis zu zehn Minuten zeitlich versetzt.
- Jeder Lauf prüft CT126-Isolation, aktuelle NFS-Sicherung (48h),
  existierende verifizierte Ledger-Tabelle, negative Dokument-ACLs,
  aktuelle Sichtbarkeitsrechte und maximal **25 neue + 25 entzogene**
  selbstverwaltete Rechte.
- Innerhalb jedes Laufs: Read-only-Plan und präzise gegen exakt diesen
  Plan abgeglichenes transaktionales Apply.
- Bei Ausfall, Population-/Versionswechsel, fehlender Sicherung,
  unbestätigtem Ledger oder Überschreitung des Budgets **keine Änderung**.
  Weitere aktive Paperless-Jobs bleiben unangetastet.

Für die Produktion ist zusätzlich mindestens ein kontrollierter
Test mit künstlich neuem Tag und neuem *berechtigt sichtbarem*
Dokumenttyp/Korrespondenten sowie einem Fall mit *wegfallender*
Zuordnung erforderlich. Erst nach überprüfter Rücknahme eigener
Test-Grants den Timer freigeben.

## Unabhängiger offener Fehler

Der native Paperless-KI-Chat im Browser zeigt weiter
\`Error receiving response.\`. Die Nginx-Streaming-Korrektur wurde
bereits angewendet und geprüft, war allein aber nicht ausreichend.
Die Metadaten-Reconciliation ändert **keine** KI-Chat-Komponente.
