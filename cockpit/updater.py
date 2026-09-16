"""Updates (Spez 6.12): zuerst GitHub-Releases des öffentlichen Repos, ersatzweise der Ordner
«Updates» im Datenordner (Zip von Hand abgelegt). Das Paket ersetzt sich nicht selbst, solange es
läuft: ein kleines Skript wartet auf das Ende des Prozesses, tauscht den Ordner und startet neu."""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .version import VERSION, GITHUB_REPO

ASSET_MUSTER = re.compile(r"HelferCockpit-(\d+\.\d+\.\d+)-windows\.zip$", re.IGNORECASE)


def version_tuple(v):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def ist_neuer(kandidat, aktuell=VERSION):
    return version_tuple(kandidat) > version_tuple(aktuell)


def app_ordner():
    """Ordner mit start.py — bei installierten Paketen …\\HelferCockpit\\app."""
    return Path(__file__).resolve().parent.parent


def ist_entwicklung(app=None):
    return ((app or app_ordner()) / ".git").exists()


def pruefe_github(repo=GITHUB_REPO, timeout=8):
    """Neueste Version auf GitHub. Liefert dict oder None (kein Internet, kein Release)."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "helfer-cockpit"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    for a in d.get("assets") or []:
        if ASSET_MUSTER.search(a.get("name", "")):
            return {"version": d.get("tag_name", "").lstrip("v"), "quelle": "github",
                    "url": a.get("browser_download_url"), "name": a["name"],
                    "notizen": (d.get("body") or "").strip()[:2000], "groesse": a.get("size")}
    return None


def pruefe_ordner(updates_dir):
    """Neueste Zip-Version im Ordner «Updates» des Datenordners."""
    beste = None
    try:
        for p in Path(updates_dir).iterdir():
            m = ASSET_MUSTER.search(p.name)
            if m and (beste is None or ist_neuer(m.group(1), beste["version"])):
                beste = {"version": m.group(1), "quelle": "ordner", "pfad": str(p), "name": p.name, "notizen": ""}
    except OSError:
        return None
    return beste


def pruefe(updates_dir=None, repo=GITHUB_REPO):
    """Gesamtbild für die Oberfläche: aktuelle Version, ob neuer verfügbar, woher."""
    gh = pruefe_github(repo)
    lokal = pruefe_ordner(updates_dir) if updates_dir else None
    kandidaten = [k for k in (gh, lokal) if k and ist_neuer(k["version"])]
    kandidaten.sort(key=lambda k: version_tuple(k["version"]), reverse=True)
    return {"aktuell": VERSION, "github_erreichbar": gh is not None, "ordner_geprueft": bool(updates_dir),
            "neu": kandidaten[0] if kandidaten else None, "entwicklung": ist_entwicklung()}


def zip_pruefen(zip_pfad):
    """Das Zip muss das Paket enthalten: <Wurzel>/cockpit/version.py. Liefert die Wurzel."""
    with zipfile.ZipFile(zip_pfad) as z:
        namen = z.namelist()
        for n in namen:
            teile = n.split("/")
            if len(teile) >= 3 and teile[1] == "cockpit" and teile[2] == "version.py":
                return teile[0]
    raise ValueError("Das Zip enthält kein Helfer-Cockpit-Paket (cockpit/version.py fehlt).")


def herunterladen(url, ziel, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "helfer-cockpit"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(ziel, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return ziel


def entpacken(zip_pfad, ziel_neu):
    """Nach <app>.new entpacken (Wurzelordner des Zips wird abgestreift)."""
    wurzel = zip_pruefen(zip_pfad)
    ziel_neu = Path(ziel_neu)
    if ziel_neu.exists():
        import shutil
        shutil.rmtree(ziel_neu)
    ziel_neu.mkdir(parents=True)
    with zipfile.ZipFile(zip_pfad) as z:
        for info in z.infolist():
            rel = info.filename[len(wurzel) + 1:] if info.filename.startswith(wurzel + "/") else None
            if not rel:
                continue
            ziel = ziel_neu / rel
            if info.is_dir():
                ziel.mkdir(parents=True, exist_ok=True)
            else:
                ziel.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as q, open(ziel, "wb") as f:
                    f.write(q.read())
    return ziel_neu


def tausch_skript_schreiben(app, neu, pid, starter):
    """Skript, das nach dem Ende dieses Prozesses den Ordner tauscht und neu startet."""
    app, neu = Path(app), Path(neu)
    alt = app.with_name(app.name + ".alt")
    if sys.platform == "win32":
        pfad = app.parent / "update.bat"
        pfad.write_text("\r\n".join([
            "@echo off",
            f":warten",
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL && (timeout /t 1 /nobreak >NUL & goto warten)',
            f'if exist "{alt}" rmdir /s /q "{alt}"',
            f'move "{app}" "{alt}" >NUL',
            f'move "{neu}" "{app}" >NUL',
            f'if exist "{alt}" rmdir /s /q "{alt}"',
            f'start "" "{starter}"',
            'del "%~f0"',
        ]) + "\r\n", encoding="utf-8")
        return pfad
    pfad = app.parent / "update.sh"
    pfad.write_text("\n".join([
        "#!/bin/sh",
        f"while kill -0 {pid} 2>/dev/null; do sleep 1; done",
        f'rm -rf "{alt}"',
        f'mv "{app}" "{alt}" && mv "{neu}" "{app}" && rm -rf "{alt}"',
        f'"{starter}" &',
        'rm -f "$0"',
    ]) + "\n", encoding="utf-8")
    os.chmod(pfad, 0o755)
    return pfad


def installieren(kandidat, konfig_dir):
    """Zip beschaffen, prüfen, neben den App-Ordner entpacken und das Tausch-Skript starten.
    Liefert den Pfad des Skripts; der Aufrufer beendet danach den Server."""
    app = app_ordner()
    if ist_entwicklung(app):
        raise RuntimeError("Dies ist ein Entwicklungs-Checkout (Git) — Update bitte mit «git pull».")
    konfig_dir = Path(konfig_dir); (konfig_dir / "updates").mkdir(parents=True, exist_ok=True)
    if kandidat.get("quelle") == "github":
        zip_pfad = herunterladen(kandidat["url"], konfig_dir / "updates" / kandidat["name"])
    else:
        zip_pfad = Path(kandidat["pfad"])
    neu = entpacken(zip_pfad, app.with_name(app.name + ".new"))
    starter = neu / ("Helfer-Cockpit.bat" if sys.platform == "win32" else "Helfer-Cockpit starten.command")
    starter_final = app / starter.name
    skript = tausch_skript_schreiben(app, neu, os.getpid(), starter_final)
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", str(skript)], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)
    else:
        subprocess.Popen(["/bin/sh", str(skript)], start_new_session=True, close_fds=True)
    return skript
