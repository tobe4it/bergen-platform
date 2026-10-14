<!-- bergen-platform-handbook: managed -->
# Private Übergabe und Notfallblatt

[Deutsch](DE-Handover.md) | [English](EN-Handover.md)

## Drei getrennte Unterlagen

1. **Öffentliches Handbuch:** Grundlagen und verallgemeinerte Vorgehensweisen.
2. **Privater Betriebsbogen:** Hosts/IDs, URLs, Datenpfade, Kontakte, Verträge, Netzplan, Sicherungs- und Restore-Nachweise.
3. **Notfallblatt:** Nur notwendige Entschlüsselungs-/Wiederherstellungswerte, die nicht aus einem Vault oder Passwortmanager erreichbar sind. Das ausgefüllte Blatt bleibt offline.

## Leere Druckvorlage

[Notfallblatt Deutsch: PDF herunterladen](https://github.com/tobe4it/bergen-platform/raw/refs/heads/main/docs/handbook/print/Emergency-Secrets-DE.pdf)

[Englische Vorlage](https://github.com/tobe4it/bergen-platform/raw/refs/heads/main/docs/handbook/print/Emergency-Secrets-EN.pdf)

Zwei A4-Seiten: Die erste hält Zugriffsweg, Vault-Entschlüsselung und gegebenenfalls lokale Notfallanmeldung fest. Die zweite bietet Felder für Entschlüsselung, MFA-Wiederherstellung und weitere begründete Ausnahmen. Nicht jedes Feld muss einen geheimen Wert enthalten; nicht benötigte Felder streichen.

## Sparsam ausfüllen

Für bereits im Vault/Passwortmanager gesicherte Einträge genügt der Verweis. Den vollständigen Inhalt eines Vaults oder private Schlüssel nicht auf das Blatt kopieren. Ein Vault kann nicht den einzigen erreichbaren Nachweis seines eigenen Entschlüsselungsgeheimnisses enthalten.

Eine zweite Person testet den vorgesehenen Zugriff, ohne zusätzliche Werte aus dem Gedächtnis des bisherigen Administrators. Sie prüft dann eine isolierte Wiederherstellung wichtiger Daten. Anmeldung, laufende Sicherung und erfolgreicher Restore werden getrennt dokumentiert.

Ausgefüllte Blätter nicht fotografieren, einscannen oder in Wiki, Git, Issues, Pull Requests oder Chat hochladen. Aufbewahrungsort, berechtigte Personen, Ersatzkopie und Prüfdatum privat erfassen. Nach einer Änderung veraltete Kopien nach der vereinbarten Regel ersetzen.

## Mindestinhalt des privaten Betriebsbogens

| Thema | Einzutragen |
| --- | --- |
| Dienst | Aufgabe, produktiv/vorbereitet/Labor, Host/ID, URL und Version |
| Netzwerk | Bridge/VLAN, Subnetz, DNS, Reservierung und erlaubter Verwaltungsweg |
| Daten | Dokument-/Mailboxpfad, Datenbank und externe Mountpoints |
| Sicherung | Job, Ziel, Umfang, Zeitplan, Aufbewahrung und Schlüssel-Verweis |
| Restore | Isoliertes Ziel, Version, Datum, Stichproben, Dauer und Ergebnis |
| Verantwortung | Betreuung, Vertretung und unabhängiger Kontaktweg |
| Verträge | Anbieter, Funktion, Frist und private Ablage der Unterlagen |

[Inhalt](DE-Start.md) · [Backup und Restore](DE-Backup-Recovery.md)
