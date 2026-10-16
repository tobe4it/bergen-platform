<!-- bergen-platform-handbook: managed -->
# Bergen-Platform für Einsteiger

[Deutsch](DE-Start.md) | [English](EN-Start.md)

Sie müssen kein Linux-Experte sein, um die Plattform sinnvoll zu nutzen und eine Übergabe vorzubereiten. Dieses Handbuch erklärt, welche Aufgabe jedes System hat, wie Abhängigkeiten funktionieren und wann eine eingewiesene Betreuungsperson benötigt wird.

## Vier Lesepfade

- **Noch keine eigene Umgebung?** [Selbst betriebene IT von Grund auf aufbauen](DE-Self-Hosting.md): Voraussetzungen verstehen, im Labor üben, die erste Installation prüfen und schrittweise erweitern.
- **Ausfall oder Nachlass:** Soforthilfe lesen, Ansprechpartner und privaten Notfallzugang suchen, vorhandene Daten erhalten.
- **Alltägliche Nutzung:** Anwendungsseiten lesen, berechtigte persönliche Zugänge verwenden und Fehler genau beschreiben.
- **Betreuung übernehmen:** Grundlagen, Automation und Backup durcharbeiten, privaten Bestand erfassen und eine isolierte Wiederherstellung nachweisen.

## Inhalt

**Neu anfangen:** [Lern- und Aufbaupfad für selbst betriebene IT](DE-Self-Hosting.md).

1. [Soforthilfe](DE-Emergency.md)

2. [Architektur](DE-Architecture.md)

3. [Netzwerk und Identität](DE-Network-Identity.md)

4. [Linux und Container](DE-Linux-Containers.md)

5. [Automation und Geheimnisse](DE-Automation-Secrets.md)

6. [Anwendungen](DE-Applications.md)

7. [Backup und Restore](DE-Backup-Recovery.md)

8. [Betrieb und Übernahme](DE-Operations.md)

9. [Private Übergabe und Druckvorlage](DE-Handover.md)

10. [Wörterbuch](DE-Glossary.md)

11. [Quellen](DE-Sources.md)

## Was öffentlich steht und was privat bleibt

Diese Ausgabe beschreibt die verfügbare Architektur und überprüfbare Abläufe. Sie enthält keine wirklichen Standortadressen, privaten Domainnamen oder Zugangsdaten. Reine Beispiele verwenden `example.test` und `192.0.2.0/24`.

Eine implementierte Rolle, ein erfolgreicher Ansible-Lauf und eine im Alltag abgenommene Funktion sind unterschiedliche Nachweise. Geplante, vorbereitete und produktive Komponenten ausdrücklich unterscheiden. Ein Backup wird erst durch einen erfolgreichen Restore belastbar.

Die separate Druckvorlage ist nur für die wenigen nötigen Geheimnisse außerhalb der Vaults beziehungsweise des Passwortmanagers bestimmt. Ausdrucken, offline von Hand ergänzen und geschützt aufbewahren. Bereits gesicherte Werte nur referenzieren.

Ausgabe 1.0, 14.10.2026. [Quellen und Pflege](DE-Sources.md).
