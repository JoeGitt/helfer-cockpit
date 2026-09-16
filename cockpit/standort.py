"""Standort der gemeinsamen Daten (Spez 6.12): Regeln, gemerkte Antworten, Verlauf und Ausgabe liegen
in einem Datenordner — beim Verein auf dem Netzlaufwerk, damit alle am gleichen Stand arbeiten.
Pro Benutzer merkt sich das Cockpit nur den Pfad (~/.helfer-cockpit/standort.json); der API-Key
liegt im Schlüsselbund des Betriebssystems, nie im Datenordner und nie im Paket."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KONFIG = Path.home() / ".helfer-cockpit"
STANDORT_DATEI = KONFIG / "standort.json"
UNTERORDNER = ("Ausgabe", "Updates")


def lade_standort():
    """Gespeicherter Datenordner oder None."""
    try:
        d = json.loads(STANDORT_DATEI.read_text(encoding="utf-8"))
        p = d.get("daten_ordner")
        return Path(p) if p else None
    except (OSError, ValueError, AttributeError):
        return None


def speichere_standort(daten_ordner):
    KONFIG.mkdir(parents=True, exist_ok=True)
    tmp = STANDORT_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps({"daten_ordner": str(daten_ordner)}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STANDORT_DATEI)


def pruefe_ordner(pfad):
    """Ordner prüfen und vorbereiten. Liefert (ok, meldung). Legt Unterordner an und testet das Schreiben —
    ein Netzlaufwerk ohne Schreibrecht wäre sonst erst beim Abgleich ein Problem."""
    text = (pfad or "").strip().strip('"')
    if not text:
        return False, "Bitte einen Ordner angeben."
    p = Path(os.path.expanduser(text))
    if not p.is_absolute():
        return False, "Bitte einen vollständigen Pfad angeben (z. B. \\\\server\\verein\\HelferCockpit oder /Volumes/…)."
    try:
        p.mkdir(parents=True, exist_ok=True)
        for u in UNTERORDNER:
            (p / u).mkdir(exist_ok=True)
        test = p / ".schreibtest"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
    except OSError as e:
        return False, f"Ordner nicht nutzbar: {e}"
    return True, str(p)


def uebernehme_alte_dateien(daten_ordner, alt_konfig=KONFIG, alt_ausgabe=None):
    """Einmalige Übernahme: Regeln/Verlauf aus ~/.helfer-cockpit und die bisherige Ausgabe, wenn der
    neue Datenordner noch leer ist. Nichts wird überschrieben."""
    uebernommen = []
    ziel = Path(daten_ordner)
    for name in ("regeln.json", "protokoll.jsonl"):
        q, z = Path(alt_konfig) / name, ziel / name
        if q.exists() and not z.exists():
            shutil.copy2(q, z); uebernommen.append(name)
    if alt_ausgabe and Path(alt_ausgabe).is_dir() and Path(alt_ausgabe).resolve() != (ziel / "Ausgabe").resolve():
        for q in Path(alt_ausgabe).iterdir():
            z = ziel / "Ausgabe" / q.name
            if q.is_file() and not z.exists():
                shutil.copy2(q, z); uebernommen.append(f"Ausgabe/{q.name}")
    return uebernommen


def ordner_dialog(start=None):
    """Nativen Ordner-Dialog öffnen (Windows: PowerShell, macOS: AppleScript). None = abgebrochen/nicht möglich."""
    try:
        if sys.platform == "win32":
            skript = ("Add-Type -AssemblyName System.Windows.Forms; "
                      "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                      "$d.Description = 'Datenordner des Helfer-Cockpits wählen (z. B. auf dem Netzlaufwerk)'; "
                      "$d.ShowNewFolderButton = $true; "
                      + (f"$d.SelectedPath = '{start}'; " if start else "")
                      + "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", skript],
                               capture_output=True, text=True, timeout=300)
            pfad = (r.stdout or "").strip()
            return pfad or None
        if sys.platform == "darwin":
            r = subprocess.run(["osascript", "-e",
                                'POSIX path of (choose folder with prompt "Datenordner des Helfer-Cockpits wählen")'],
                               capture_output=True, text=True, timeout=300)
            pfad = (r.stdout or "").strip().rstrip("/")
            return pfad or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None
