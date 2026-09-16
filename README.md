# Helfer-Cockpit 2

Lokales Werkzeug der Pfadi Winterthur Handball: Kontingent-Erfüllung der Mitglieder aus dem
Helfereinsatz-Portal und geführter Mitglieder-Abgleich Fairgate → Portal. Läuft auf dem eigenen
Rechner, Oberfläche im Browser. Keine Personendaten im Programmpaket und in diesem Repository.

## Installation auf Windows (ohne Admin-Rechte)

1. Diese Datei herunterladen und doppelklicken: **[Installieren.bat](packaging/Installieren.bat)**
   (Rechtsklick → «Ziel speichern unter»). Alternativ in PowerShell:
   ```
   irm https://raw.githubusercontent.com/JoeGitt/helfer-cockpit/main/packaging/install.ps1 | iex
   ```
   Der Installer lädt das neueste Paket von GitHub nach `%LOCALAPPDATA%\HelferCockpit\app`, legt die
   Verknüpfung «Helfer-Cockpit» auf den Desktop und ins Startmenü und startet das Cockpit.
   Windows SmartScreen kann beim ersten Start nachfragen («Weitere Informationen» → «Trotzdem ausführen»).
2. Im Browser öffnet sich die **Einrichtung**:
   - **Datenordner** wählen — beim Verein ein Ordner auf dem Netzlaufwerk (z. B. `\\server\verein\HelferCockpit`).
     Dort liegen Regeln, gemerkte Antworten, Verlauf und der Ordner «Ausgabe». Alle arbeiten damit am gleichen Stand.
   - **API-Key** des Helferportals einfügen (Organisation → API, Leserecht genügt). Der Key wird im
     Schlüsselbund des angemeldeten Windows-Benutzers gespeichert — nie im Datenordner, nie im Paket.
     Jede Person, die das Cockpit benutzt, gibt ihn einmal ein.
3. «Cockpit starten». Danach genügt die Desktop-Verknüpfung.

Das Paket bringt eine eigene Python-Kopie mit; es muss nichts vorinstalliert sein. Meldungen ohne
Konsole landen in `%USERPROFILE%\.helfer-cockpit\cockpit.log`; «Helfer-Cockpit Konsole.bat» startet mit
sichtbarem Fenster zur Fehlersuche.

## Update

Einstellungen → **Über & Update** → «Nach Update suchen». Gefunden wird die neueste Version auf GitHub;
ohne Internet der Ordner `Updates` im Datenordner (dort ein `HelferCockpit-<Version>-windows.zip`
ablegen). «Jetzt aktualisieren» lädt das Paket, beendet das Cockpit, tauscht den Programmordner und
startet neu. Datenordner und API-Key bleiben unberührt.

Neue Version veröffentlichen (Entwickler): `VERSION` in `cockpit/version.py` erhöhen, committen,
Tag `v<Version>` pushen — GitHub Actions baut das Windows-Paket und hängt es ans Release.
Lokal bauen: `python3 packaging/build_release.py` → `dist/HelferCockpit-<Version>-windows.zip`.

## macOS / Entwicklung

```
pip install openpyxl keyring pytest
python3 start.py              # normal, Einrichtung beim ersten Start im Browser
python3 start.py --demo       # fiktive Daten, ohne API-Key
python3 start.py --pseudo     # pseudonymisierter Bestand (tests/fixtures/pseudo, nicht im Repo)
python3 start.py --key-reset  # gespeicherten Key verwerfen
python3 -m pytest -q
```
Doppelklick: `Helfer-Cockpit starten.command`. Konfiguration pro Benutzer in `~/.helfer-cockpit/`
(Standort des Datenordners, Log). Spezifikation: `../SPEZIFIKATION-helfer-cockpit-2.md`.
