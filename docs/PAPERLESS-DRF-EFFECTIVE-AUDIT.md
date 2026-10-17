# Paperless: effektiver DRF-API-Berechtigungstest (Read-only)

Dieser Prüfpfad ergänzte die in `main` bereits veröffentlichte Django-Rechteübersicht, **ohne sie zu ersetzen**. Nachfolgestand zu [PR #62](https://github.com/tobe4it/bergen-platform/pull/62), ursprünglich am 14.10.2026 anhand von vier Dokumenten und drei Identitäten mit 36/36 bestandenen Einzelprüfungen berichtet. Der damalige Betreiberbefund ist ein historischer Nachweis, **keine automatische Zusage**, dass heutige neue Dokumente ebenso geschützt sind.

## Schutzgrenzen

Nur `GET` durch DRF `APIClient.force_authenticate` im laufenden Paperless-Prozess. Weder Zugangstoken noch PDF-Dateien werden exportiert. Geprüft werden für vier aktuelle, vom Betreiber ausgewählte Dokumente je drei nichtadministrative Konten: Detail, Download und die komplette ungepaginierte Sichtbarkeitsliste (36 Checks). Jeder Test-Scope benötigt mindestens eine positive und eine negative Erwartung, und fehlende Benutzer/Dokumente führen zu FAIL. Ein fehlgeschlagener Audit kann keinen Produktionsdienst verändern.

**Nicht abgedeckt:** echter OIDC-/LDAP-Login, Proxy-Session, weitere Endpunkte/Suche/Vorschau, Kinderkonten, Dokumente außerhalb der zwölf Fälle sowie AI/RAG-Tools. Insbesondere ist die Ausgabe `DRF_AUTHORIZATION_FAILURES=0` **keine Freigabe** einer Paperless-KI. Identitätsdelegation und negative KI-End-to-End-Tests bleiben in PR #63.

## Nutzung in bestehender Installation

Vier **aktuelle** Dokument-IDs und drei bestehende reguläre Paperless-Identitäten ausschließlich in einer **ignorierten** Site-Datei `ansible/vars/paperless-acl.local.yml` eintragen. Die Beispielstruktur unter `docs/examples/paperless-acl.local.yml.example` enthält keine reale Identität. Jede Kombination aus Dokument und Nutzer muss exakt einmal vorkommen; eigene Erwartungen erst nach Prüfung der tatsächlich beabsichtigten ACL-Policy festlegen. Der Audit ist strikt nur lesend; er benötigt keine Apply-Freigabe.

```bash
cd ~/bergen-platform
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-effective-drf-readonly.yml \
  -e @ansible/vars/paperless-acl.local.yml \
  --syntax-check
ansible-playbook -i ansible/inventory.yml -i ansible/inventory.local.yml \
  ansible/playbooks/audit-paperless-effective-drf-readonly.yml \
  -e @ansible/vars/paperless-acl.local.yml
```

Wegen der vertraulichen Identitäten und Dokument-IDs verwendet die Ansible-Ausführung `no_log`; nur der aggregierte Erfolgsstatus wird angezeigt. Die Quellmatrix darf weder eingecheckt noch in Support-Chats kopiert werden.

Die ältere in #62 gespeicherte fallgenaue API-Prüfung bleibt über dessen Git-Historie zugänglich; dieses Playbook ersetzt hartkodierte Bestandskonten durch die lokale explizite Fallmatrix und vermeidet das Drucken aller Nutzernamen und Objektgrants.
