# Helfer-Cockpit 2

Lokales Verwaltungstool für Einsatzdaten der Handball-Gruppe.

## Voraussetzung

Python 3.10 oder neuer muss installiert sein:
1. Downloaden von [python.org](https://www.python.org/downloads/) (Windows: «Add to PATH» ankreuzen)
2. Terminal/Eingabeaufforderung öffnen, einmalig eingeben:
   ```
   pip install openpyxl keyring
   ```

## Start

**Windows:** Doppelklick auf `Helfer-Cockpit starten.bat`  
**macOS:** Doppelklick auf `Helfer-Cockpit starten.command`

Das Dashboard öffnet sich automatisch im Browser. Das Fenster offen lassen (Schliessen beendet das Cockpit).

## Erststart

Beim ersten Start wird der API-Key abgefragt. Dieser wird sicher im Betriebssystem gespeichert.  
*Der Key ist read-only und kann jederzeit im Portal widerrufen werden.*

## Optionen

Zum Testen ohne API-Key (mit Beispieldaten):
```
python3 start.py --demo
```

Um den API-Key neu zu erfassen:
```
python3 start.py --key-reset
```

## Ausgabedateien

Exportierte Reports und Listen werden im Ordner `Ausgabe/` gespeichert.

## Saisonabschluss – Wichtig!

**Reihenfolge beachten:**
1. Alle Reports exportieren (`Ausgabe/`)
2. Danach: Events in der Quelle zurücksetzen

*Umgekehrte Reihenfolge führt zu Datenverlust.*
