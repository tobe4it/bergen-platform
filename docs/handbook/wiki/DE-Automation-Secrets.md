<!-- bergen-platform-handbook: managed -->
# Git, Ansible und Notfallzugang

[Deutsch](DE-Start.md) | [English](EN-Automation-Secrets.md)

**Öffentliche Ausgabe 1.0, 14.10.2026.** Beispiele ersetzen keine private Standortkonfiguration.

## Git: der nachvollziehbare Bauplan

Git bewahrt Änderungen an Programmcode und Konfiguration auf. GitHub stellt das gemeinsame Projekt bereit; eine lokale Arbeitskopie liegt auf dem Controller.

### Repository, Commit und Branch
Git bewahrt Änderungen an Code und Vorlagen. Ein Repository enthält Projekt und Historie; ein Commit ist ein festgehaltener Stand; ein Branch eine Entwicklungslinie; ein Tag kann eine Veröffentlichung markieren. Pull Requests erlauben die Prüfung vor der Übernahme.

Das öffentliche Projekt ist `tobe4it/bergen-platform`. Der Quellstand für diese Wiki-Ausgabe steht auf der Quellenseite. Er beweist nicht, dass jeder Dienst oder Controller auf diesem Stand läuft. Private Arbeitskopien und Feature-Branches können anders sein.

### Erste Prüfung auf dem Controller
Die folgenden lesenden Befehle im tatsächlichen Projektverzeichnis ausführen:

```sh
git status --short
git branch --show-current
git log -1 --oneline
```

Leerer Kurzstatus bedeutet keine von Git erkannten Änderungen. Branch und Commit getrennt notieren. `git fetch` holt neue Projektinformationen; ein `git pull --ff-only` kann die Arbeitskopie ändern. Die Anwendung wird dadurch noch nicht automatisch aktualisiert; ein passender Ansible-Aufruf ist ein eigener Schritt.

### Private Dateien sind nicht automatisch gesichert
`.gitignore` verhindert die normale Aufnahme bestimmter Dateien. Ignoriert bedeutet weder verschlüsselt noch gesichert. Privates Inventory, Standortvariablen, lokale Vault-Dateien und SSH-Material gehören ausdrücklich in die geschützte Controller-Sicherung. Niemals mit einem Reset unbekannte lokale Änderungen beseitigen.


## Ansible: wiederholbare Einrichtung

Ansible führt beschriebene Aufgaben auf ausgewählten Systemen aus. Ein erfolgreicher Lauf ersetzt weder den Funktionstest einer Anwendung noch eine Sicherung.

### Die Bausteine
**Inventory:** Welche Hosts und Gruppen gibt es? **Variablen:** Welche Standortwerte gelten? **Playbook:** Welche Aufgaben laufen in welcher Reihenfolge? **Role:** Wiederverwendbarer Aufgabenblock. **Template:** Konfigurationsvorlage. **Vault:** verschlüsselte geheime Werte.

Der Controller verwendet öffentliches und privates Inventory gemeinsam. Die konkrete Transportart kann direktes SSH oder Proxmox-vermittelter Zugriff sein. Fehlende direkte Erreichbarkeit eines LXC ist deshalb nicht automatisch falsch.

### Das Arbeitsumfeld
Eine Python-**venv** hält Projektabhängigkeiten getrennt vom übrigen System. Der Prompt `(.venv)` ist nur ein Hinweis auf eine aktivierte Umgebung. In bisherigen Anleitungen tauchen unterschiedliche venv-Pfade auf; für die Übernahme den tatsächlich verwendeten Pfad festhalten.

### Was die Ergebniszeilen bedeuten
| Ergebnis | Bedeutung |
| --- | --- |
| ok | Aufgabe ohne gemeldete Änderung abgeschlossen |
| changed | Aufgabe hat eine Änderung vorgenommen |
| failed | Eine Aufgabe ist fehlgeschlagen |
| unreachable | Ansible konnte den Host nicht passend erreichen |
| skipped | Aufgabe wurde wegen Bedingungen übersprungen |

**Idempotent** bedeutet: Derselbe gewünschte Zustand soll beim erneuten Lauf möglichst ohne neue Änderungen entstehen. Das macht einen Lauf nicht automatisch gefahrlos; Variablen oder Softwarestände können inzwischen anders sein.

### Prüfmodi richtig einordnen
`--syntax-check` prüft die Playbook-Syntax. `--check` versucht eine Vorschau; nicht jede Aufgabe unterstützt sie vollständig. `--diff` zeigt Unterschiede und kann geheime Werte offenlegen, wenn die Aufgabe nicht passend geschützt ist.

Vor jedem ändernden Lauf müssen Zielgruppe, private Variablen, Version, Wirkung und Rückkehrplan klar sein. Keine allgemeine Bootstrap-Anleitung auf Verdacht starten. Für Angehörige genügt: Den Controller bewahren und die Betreuung die passende, dokumentierte Teilaufgabe ausführen lassen.

**Lernprobe:** `failed=0` beweist keinen externen Mail-Rundlauf. Dazu muss eine echte Testmail hin und zurück funktionieren.

## Geheimnisse und Notfallzugänge

Dieses Handbuch erklärt, welche Zugänge nötig sind. Die geheimen Werte liegen in einem getrennten, geschützten Notfallpaket.

### Vier Dinge getrennt aufbewahren
**Passwörter** melden Konten an. **Private SSH-Schlüssel** erlauben Verwaltungszugriff. Das **Vault-Passwort** entschlüsselt Ansible-Geheimnisse. **MFA/2FA-Mittel** wie Sicherheitsschlüssel oder Wiederherstellungscodes vervollständigen manche Anmeldungen.

Ansible Vault verschlüsselt gespeicherte Inhalte. Für die Ausführung entschlüsselt Ansible benötigte Werte; daraus folgt kein Schutz aller späteren Ausgaben und Laufzeitdateien. Wer nur die verschlüsselte Datei besitzt, hat ohne das passende Geheimnis keinen nutzbaren Zugang.

### Das getrennte Notfallpaket vorbereiten
- Zugänge zu Router/UniFi, Synology, Proxmox und Controller einschließlich lokaler Notfalladministration.
- Domain-/DNS-Verwaltung, externer Mail-Gateway, Internetvertrag und gegebenenfalls weitere Dienstanbieter.
- GitHub-Zugriff für Betreuung und private Standortkonfiguration; das öffentliche Repository bleibt nur ein Teil des Bauplans.
- Vault-Datei samt getrenntem Entschlüsselungsweg, SSH-Schlüssel samt Passphrasen und vorhandene Backup-Schlüssel.
- MFA-Wiederherstellung und ein erreichbarer Kontaktweg, der nicht allein vom selbst gehosteten Mailserver abhängt.

Im öffentlichen Wiki und im allgemeinen Übergabebogen nur den **Aufbewahrungsort** eintragen. Die separate leere Druckvorlage wird offline von Hand mit den tatsächlich fehlenden Geheimnissen ergänzt; ausgefüllte Blätter niemals hochladen. Auch ein Passwortmanager braucht eine dokumentierte Notfallöffnung; der bloße Produktname reicht nicht.

### Anmeldung nicht von einem Gerät abhängig machen
Prüfen, ob die erforderlichen Konten ausschließlich über das Telefon oder Postfach des bisherigen Administrators wiederherstellbar sind. Die Betreuung muss ihren eigenen Zugriff unter Aufsicht erfolgreich testen. Danach Änderungen an Berechtigungen und Geheimnissen geordnet planen.

### Zertifikate sind keine Passwörter
Ein öffentliches Zertifikat beschreibt Namen und Vertrauenskette. Der dazugehörige private Schlüssel ist geheim. Eine Prüfung darf den öffentlichen Teil zeigen; der private Schlüssel darf nicht zur Diagnose veröffentlicht werden.

**Übergabenachweis:** Eine zweite Person kann mit dem vorgesehenen Verfahren die nötigen Systeme erreichen, ohne dass der bisherige Administrator live helfen muss. Das Ergebnis im privaten Übergabebogen eintragen.

---

[Inhalt](DE-Start.md) · [Quellen](DE-Sources.md) · [Private Übergabe vorbereiten](DE-Handover.md)
