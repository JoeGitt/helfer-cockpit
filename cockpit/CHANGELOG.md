# Versionshinweise Helfer-Cockpit

Neueste Version zuoberst. Jede Version: Überschrift «## <Version> — <Datum>», darunter Punkte.
Der Abschnitt einer Version wird beim Veröffentlichen zum Text des GitHub-Releases und erscheint im
Cockpit unter Einstellungen → Über & Update.

## 2.1.14 — 22.09.2026
- Versionshinweise direkt im Cockpit: Einstellungen → Über & Update zeigt, was in jeder Version neu ist.
- Nach einem Update weist das Cockpit einmal darauf hin, was sich geändert hat.
- Das Update-Angebot listet alle Änderungen seit der installierten Version, nicht nur die der neuesten.

## 2.1.13 — 22.09.2026
- Mitglied-Erkennung hängt nicht mehr von der Reihenfolge im Portal ab: Bei zwei Accounts mit derselben FG-Nummer wird der Account mit dem Namen aus Fairgate Mitglied, nie ein Elternaccount.
- Neueintritte, die sich von einem bestehenden Account nur in Gross-/Kleinschreibung unterscheiden, werden als Duplikat gemeldet statt importiert.
- Die Kontrolle lässt sich abschliessen, sobald der Import angekommen ist; offene Austritte und Klärfälle kommen beim nächsten Abgleich wieder.
- Häkchen in Schritt 2 bleiben beim richtigen Punkt, auch wenn Vorfragen wieder geöffnet werden.
- «Neu abrufen» verwendet einen neueren Fairgate-Export, den jemand anderes im Team hochgeladen hat.

## 2.1.12 — 22.09.2026
- Der letzte Fairgate-Export wird gemerkt: «Neu abrufen» gleicht automatisch neu ab, ohne erneuten Upload — auch nach einem Neustart.
- Alle Antworten «Weiss nicht» lassen sich mit einem Klick wieder als Vorfrage öffnen (Schritt 1 und Schritt 2).

## 2.1.11 — 17.09.2026
- Telefonnummern werden nur noch auf die Ziffern verglichen: Zusätze wie «Mama» oder andere Leerzeichen lösen keine Korrektur mehr aus.
- In die Import-Datei kommen Telefonnummern nur noch mit Ziffern und Leerzeichen, wie es das Portal verlangt.

## 2.1.10 — 16.09.2026
- Vereinslogo als Desktop-Symbol und als Symbol im Browser-Tab.

## 2.1.9 — 16.09.2026
- Ausgabedateien mit Personendaten werden nach 90 Tagen automatisch gelöscht; die Frist ist unter Einstellungen → Regeln einstellbar.

## 2.1.8 — 16.09.2026
- Selbst-Update unter Windows läuft zuverlässig und ohne sichtbares Fenster (Korrekturen aus 2.1.4 bis 2.1.7).

## 2.1.2 — 16.09.2026
- Sicherheit: Das Update lädt nur Pakete, die das Cockpit selbst gefunden hat, prüft Zip-Inhalte und nimmt keine Befehle von fremden Webseiten an.

## 2.1.0 — 16.09.2026
- Erste installierbare Version für Windows: Installer ohne Admin-Rechte, eigenes Python im Paket, Desktop-Verknüpfung.
- Einrichtung beim ersten Start: gemeinsamer Datenordner auf dem Netzlaufwerk und API-Key im Schlüsselbund des Benutzers.
- Selbst-Update über Einstellungen → Über & Update.
- Mitglieder-Abgleich mit Vorfragen vor der Import-Datei, Familien-Topf für Geschwister und Ansicht «Helfende» nach Mitglied oder Account.
