# Bergen Paperless-ngx: Berechtigungsmodell für die Dokumentenarchive

Status: **fachlich freigegeben, technisch noch nicht ausgerollt** (2026-10-14).
Die bestehende Synology-Einlieferung und die Paperless-Timer bleiben unverändert.

## Ziele und Eigentümerschaft

Paperless verwendet für `Document.owner` genau **einen** User, keine Gruppe
und keine Mehrfacheigentümer. Für gemeinsame Dokumente bleibt der technische
Paperless-Benutzer `admin` Eigentümer; wir machen weder Thomas noch Nadja
zum alleinigen Eigentümer von gemeinsamen Familien- oder Elternunterlagen.

| Bereich | Eigentümer | Lesen | Bearbeiten | Löschen |
| --- | --- | --- | --- | --- |
| Privat/thomas | thomas | thomas, Superuser | thomas | thomas |
| Privat/nadja | nadja | nadja, Superuser | nadja | nadja |
| Privat/<kind> nach Freischaltung | jeweiliges Kind | Kind, Superuser | Kind | Kind (eigene Dokumente) |
| Eltern | admin | effektive Gruppe Eltern | Thomas und Nadja | **Kein regulärer Benutzer** |
| Familie | admin | effektive Gruppe Familie | Thomas und Nadja | **Kein regulärer Benutzer** |

**Gemeinsame Archive sind vor versehentlichem Löschen geschützt.** Für
`Eltern` und `Familie` wird keine `delete_document`-Objektfreigabe
eingerichtet; auch die globale Löschberechtigung ist für den Zugriff auf
gemeinsame Dokumente nicht ausreichend. Lediglich das bestehende
administrative Konto bleibt als bewusster Ausnahme-/Wiederherstellungsweg.

Die Kinder dürfen gemeinsame Familienunterlagen lesen, aber **weder
bearbeiten noch löschen**. Ein Kind erhält seinen privaten Bereich erst nach
erfolgreicher Konten-, Gruppen-, Workflow- und ACL-Provisionierung.

## Technische Umsetzung

- **Globale Modellrechte** erlauben bestimmte API-Aktionen
  (`view_document`, `change_document`, `add_document`, bei privaten
  Eigentümern gegebenenfalls `delete_document`). Sie ersetzen **keine**
  Dokumentobjektfreigabe.
- **Objektrechte / Eigentümerrechte** bestimmen, auf welchen Dokumenten
  die jeweiligen Operationen erlaubt sind. Insbesondere keine Ausweitung
  privater Sichtbarkeit durch Mitgliedschaft in `Eltern` oder `Familie`.
- Für `Eltern` sollen `view_document` und `change_document` der
  effektiven Elterngruppe zugeordnet werden. Für `Familie` bleibt
  `view_document` auf der Familiengruppe; die individuellen
  `change_document`-Rechte werden Thomas und Nadja zugeordnet.
  **Keine** `delete_document`-Objektberechtigungen für diese Bereiche.
- Metadata-Bearbeitung (Tags, Korrespondenten, Dokumenttypen usw.)
  benötigt zusätzlich die passenden Modell- und ggf. Objektrechte.
  Kein regulärer Benutzer braucht dafür `is_staff` oder `is_superuser`.
- Die effektive Mitgliedschaft in `Familie` bzw. `Eltern` muss in der
  tatsächlichen Django/Paperless-Gruppenabbildung nachgewiesen werden.
  Verschachtelte LDAP-Gruppen gelten nur dann, wenn die Anbindung sie
  wirklich auflöst.
- Die laufende Paperless-Reconciliation erwartet derzeit nur
  `view_document` für Gruppen und nur redundante direkte Leserechte
  für aktuelle Mitglieder. **Vor** dem Erteilen von Bearbeitungsrechten
  müssen Reconciler, Workflow-Zuweisung und Tests gemeinsam umgestellt
  werden, sonst scheitert die nächste Importbestätigung.

## Getrenntes Thema: 30-Tage-Sicherheitskopien auf Synology

Das **Löschen gemeinsam genutzter Paperless-Dokumente** ist etwas anderes
als das **Entfernen einer über 30 Tage alten NAS-Scan-Sicherheitskopie**
nach verifiziertem Import und gesundem Backup. Die bereits besprochene
NAS-Kurzzeitarchiv-Retention bleibt fachlich erhalten, ist aber noch nicht
als Löschautomatik aktiviert. Der Originaldatensatz in Paperless bleibt
dabei unangetastet.

## Rollout

1. Produktive Paperless-Version und vorhandene Workflows read-only erfassen.
2. Reconciler/Tests an die *genaue* Lesebearbeitungsregel anpassen.
3. Globale Rechte und Objektfreigaben dry-run prüfen; alle derzeitigen
   und künftigen Workflow-Importe abdecken.
4. Produktivfreigabe erst nach negativen Zugriffstests: Kinder dürfen
   Familie nicht ändern/löschen; Eltern/Familie darf niemand außer dem
   Administrator löschen; fremde Privatdokumente bleiben unsichtbar.

## Persönliche UI-Einstellungen für alle regulären Paperless-Konten

Paperless-ngx 3.3.0 schützt die persönlichen UI-Einstellungen über drei
Modellberechtigungen: `view_uisettings`, `add_uisettings` und
`change_uisettings`. Diese Einstellungen betreffen immer das **angemeldete
Konto**. Im Backend wird die Speicherroutine mit
`serializer.save(user=request.user)` auf das aktuelle Konto gebunden.
`AppConfig`, Benutzerverwaltung und dokumentbezogene Rechte werden
dadurch nicht erweitert.

Die Rechte sind Bestandteil der **allgemeinen Benutzerbasis**, unabhängig von
`Mailserver`, `Eltern`, `Familie`, `Kinder`, Lese- oder Bearbeitungsrechten
auf Dokumenten.

Implementierung:
- `ansible/files/paperless/enable_personal_settings.py`:
  Idempotente Rechtevergabe an alle aktiven Nicht-Superuser, ausgenommen das
  vorhandene Sonderkonto namens `AnonymousUser`. Das `admin`-Superuserkonto
  besitzt die Rechte bereits. Auch reine Testkonten erscheinen im Dry-Run;
  gewünschte Deaktivierungen sind eine **separate** Entscheidung.
- `ansible/playbooks/prepare-paperless-personal-settings.yml`: zunächst
  ausschließlich lesende Liste der Berechtigten, anschließend nur auf
  ausdrückliche Freigabe (`-e paperless_ui_settings_apply=true`)
  transaktionale Zuteilung und Live-Verifikation.
- `tests/test_paperless_ui_settings_policy.py`: Offline-Vertragstests.

Wichtig für neue LDAP-Paperless-Konten: Die persönlichen Grundrechte müssen
bei jeder **neuen Konto-Provisionierung** ebenfalls vergeben werden. Die
derzeitige einmalige Migration installiert **keinen** automatischen
Benutzer-Erstellungs-Hook. Der Provisioning-Schritt bleibt für die geplante
LDAP-Onboarding-Automatik offen.

UI-Test nach Anwendung: Anmeldung als `thomas` oder `nadja`, Anzeige der
persönlichen Einstellungen, persönliche Änderung speichern, ohne Rechte auf
globale Anwendungsadministration oder auf Dokumente anderer Benutzer zu
erlangen.
