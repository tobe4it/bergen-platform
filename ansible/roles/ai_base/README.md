# Rolle `ai_base`

Bereitet einen Linux-LXC für lokale KI-Dienste der Bergen Platform vor.

## Aufgaben

- installiert Build- und Diagnosewerkzeuge
- erzeugt die gemeinsame Gruppe `ai`
- erzeugt Dienstbenutzer für Ollama, llama.cpp und Open WebUI
- legt gemeinsame Modell-, Daten-, Cache- und Logverzeichnisse an
- erkennt CPU-Flags, RAM, Virtualisierung und sichtbare Grafikgeräte
- stellt Hardware-Facts für nachfolgende Rollen bereit

## Nicht enthalten

- Podman
- Ollama
- llama.cpp
- Open WebUI
- Modelle

Diese Komponenten werden durch eigene Rollen installiert.

## Wichtige Variablen

- `ai_model_directory`
- `ai_data_directory`
- `ai_cache_directory`
- `ai_log_directory`
- `ai_service_users`
- `ai_group`

## Abhängigkeiten

Der Zielhost sollte zuvor mit `lxc_base` vorbereitet worden sein.
