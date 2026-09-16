# Helfer-Cockpit beim Verein einrichten — Checkliste

**Mitbringen:** nichts ausser Internet. Der API-Key wird vor Ort vom Portal-Admin erzeugt (Helfereinsatz → Organisation → API, nur Lesen).

1. **Netzlaufwerk vorbereiten:** Ordner anlegen, auf den alle Verantwortlichen Schreibrecht haben, z. B. `\\server\verein\HelferCockpit`.
2. **Installieren:** `Installieren.bat` aus dem Repo (packaging/) auf den PC laden und doppelklicken. Oder PowerShell öffnen und einfügen:
   `irm https://raw.githubusercontent.com/JoeGitt/helfer-cockpit/main/packaging/install.ps1 | iex`
   SmartScreen-Hinweis: «Weitere Informationen» → «Trotzdem ausführen».
3. **Einrichtung im Browser:** Datenordner = der Netzlaufwerk-Ordner («Ordner wählen …»), API-Key einfügen, «Cockpit starten».
4. **Regeln prüfen:** Einstellungen → Regeln (Fairgate-Kategorien, Zielwerte). Sie liegen jetzt im Datenordner.
5. **Zweiter PC / zweite Person:** Schritt 2 wiederholen, denselben Datenordner wählen, eigenen Key eingeben (oder denselben Key — er liegt pro Windows-Benutzer im Schlüsselbund).
6. **Update später:** Einstellungen → Über & Update → «Nach Update suchen» → «Jetzt aktualisieren».

**Was wo liegt**
- Programm: `%LOCALAPPDATA%\HelferCockpit\app` (wird bei Updates ersetzt)
- Datenordner (Netzlaufwerk): `regeln.json`, `entscheide.json`, `protokoll.jsonl`, `Ausgabe\`, `Updates\`
- Pro Benutzer: `%USERPROFILE%\.helfer-cockpit\standort.json` (Pfad zum Datenordner), `cockpit.log`
- API-Key: Windows-Anmeldeinformationsverwaltung (Eintrag «helfereinsatz-api»)
