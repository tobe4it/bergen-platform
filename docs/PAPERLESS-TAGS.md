# Bergen Paperless: zentraler Tag-Katalog

Ansible: `ansible/playbooks/prepare-paperless-inbox-tag.yml`

Der Katalog enthält exakt 18 administrativ verwaltete, flache Tags:

| Tags | Zuordnung |
| --- | --- |
| Steuer, Haus, Finanzen, Versicherung, Mobilität | Automatisch lernen |
| Gesundheit, Bildung, Beruf, Reise, IT | Automatisch lernen |
| Ehrenamt, Behörden, Haustiere, Energie, Gewährleistung | Automatisch lernen |
| Posteingang | Paperless-Posteingangs-Tag; kein automatisches Lernen |
| Aktion offen, Frist prüfen | Manuell; kein automatisches Lernen |

**Warum diese Trennung?** Die 15 thematischen Tags eignen sich für
Klassifizierung anhand bestätigter Beispiele. `Aktion offen` und
`Frist prüfen` sind Bearbeitungszustände, keine stabilen Themen;
eine automatische Klassifizierung wäre hier fehleranfällig.
`Posteingang` wird unabhängig vom Klassifikator beim Import vergeben.

Alle Tags werden dem Paperless-Admin zugeordnet. Aktive reguläre
Benutzer erhalten lediglich die notwendigen `view_tag`-Rechte auf
diese Tags. Die Dokument-ACLs, Eigentümer und Archivbereiche
`Privat`, `Eltern` und `Familie` bleiben unverändert. Die Tags
sind nicht automatisch in einem gemeinsamen Dokument sichtbar,
auf das der Benutzer keine Berechtigung hat.

Bei bestehenden Tags gleichen Namens stoppt die Provisionierung
bei fremder Eigentümerschaft oder unerwarteter Konfiguration,
anstatt bestehende private Tags zu übernehmen. Farben bereits
existierender Tags bleiben erhalten.

Die persönliche Option `document_editing.remove_inbox_tags`
wird nur dann auf `true` gesetzt, wenn sie noch nicht definiert
ist. Bereits gespeicherte Entscheidungen werden respektiert.
Die automatische Klassifizierung braucht zunächst genügend
korrekt manuell kategorisierte, aus dem Posteingang
herausgenommene Dokumente; sie wird nicht allein durch
das Anlegen der Tags sofort treffsicher.

## Ausführung

Zuerst den Dry-Run ausführen:

```sh
ansible-playbook \
  -i ansible/inventory.yml \
  -i ansible/inventory.local.yml \
  ansible/playbooks/prepare-paperless-inbox-tag.yml \
  --vault-id paperless@prompt \
  -e @ansible/vars/paperless.vault.yml
```

Nach Prüfung und ausdrücklicher Freigabe mit
`-e paperless_inbox_apply=true` produktiv ausführen.

Neue Benutzer erhalten die Tag-Berechtigungen noch nicht
automatisch; die Baseline-Provisionierung muss das Playbook
bei Onboarding erneut ausführen.
