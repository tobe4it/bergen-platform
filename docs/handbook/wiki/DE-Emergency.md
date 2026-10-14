<!-- bergen-platform-handbook: managed -->
# Soforthilfe

[Deutsch](DE-Start.md) | [English](EN-Emergency.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## Wenn Sie heute übernehmen müssen

Das erste Ziel ist, Internet, Kommunikation und wichtige Dateien verfügbar zu halten. Für eine geordnete Übergabe müssen Sie die Umgebung nicht sofort neu aufbauen.

### Die ersten 30 Minuten
- **Laufende Geräte eingeschaltet lassen.** Keine Werkseinstellungen, Neuinstallationen, großen Updates oder spontane Umbauten.
- Mit einem bekannten Gerät im üblichen Heim-WLAN Internet, E-Mail und Nextcloud testen. Uhrzeit und genaue Fehlermeldung aufschreiben.
- Dieses Handbuch und den getrennten Notfallzugang suchen. Den Aufbewahrungsort finden Sie nach Ergänzung im privaten Übergabebogen.
- Eine benannte Betreuungsperson hinzuziehen. Noch fehlende Telefonnummern und Zuständigkeiten stehen als auszufüllende Felder im privaten Übergabebogen.
- Rechnungen und Vertragsunterlagen für Internet, Domains, Mail-Gateway und Speicher sichern. Diese Leistungen vorerst weiterbezahlen.

### Was Sie gefahrlos selbst prüfen können
Ist Strom vorhanden? Leuchten Router, Switch und NAS wie üblich? Ist nur ein Gerät betroffen oder die ganze Familie? Funktioniert Internet über Mobilfunk, aber nicht im Heimnetz? Ist der Fehler nur beim Anmelden oder schon beim Öffnen der Seite?

Fotografieren Sie Geräte, Kabel und Fehlermeldungen für die Betreuungsperson. Sichtbare Passwörter und QR-Codes mit Zugangsinformationen dabei verdecken.

### Wann Sie aufhören sollten
Bei Festplattenwarnungen, unbekannten Zertifikatswarnungen, fehlenden Sicherungen oder Fragen nach Löschen/Überschreiben: Vorgang abbrechen und Betreuung hinzuziehen. Eine Warnung nicht einfach bestätigen, um weiterzukommen.

### Nach Stromausfall
Wenn Geräte nicht automatisch wiederkommen, soll die Betreuungsperson in dieser Reihenfolge prüfen: Netzwerk, NAS mit DNS/LDAP und Speicher, Proxmox, benötigte Anwendungen. Der Controller wird für Verwaltung gebraucht; er ersetzt keine laufende Anwendung.

Ein ausgeschaltetes Gerät normal am vorgesehenen Schalter einschalten. Ein eingeschaltetes Gerät nicht mehrfach vom Strom trennen. Bei auffälligen Geräuschen, Geruch oder elektrischen Schäden fachliche Hilfe holen.

### Nachricht an die Betreuung
„Seit __ Uhr funktioniert __ nicht. Betroffen sind __ Geräte. Internet über Mobilfunk geht/geht nicht. Letzte Änderung: __. Fehlermeldung: __. Router/NAS/Server sind eingeschaltet. Bitte zunächst Bestand und Sicherungen prüfen.“

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
