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


def pruefe_github(repo=GITHUB_REPO, timeout=8, aktuell=VERSION):
    """Neueste Version auf GitHub samt den Versionshinweisen aller Releases, die neuer sind als die
    installierte. Liefert dict oder None (kein Internet, kein Release mit Windows-Paket)."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=30",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "helfer-cockpit"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            releases = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    return auswerten(releases, aktuell)


def auswerten(releases, aktuell=VERSION):
    """Aus der Release-Liste der GitHub-API: neueste Version mit Windows-Paket und die Hinweise seit «aktuell»."""
    bester, hinweise = None, []
    for d in releases or []:
        if d.get("draft") or d.get("prerelease"):
            continue
        version = (d.get("tag_name") or "").lstrip("v")
        asset = next((a for a in d.get("assets") or [] if ASSET_MUSTER.search(a.get("name", ""))), None)
        if ist_neuer(version, aktuell):
            hinweise.append({"version": version, "text": (d.get("body") or "").strip()[:4000]})
        if asset and (bester is None or ist_neuer(version, bester["version"])):
            bester = {"version": version, "quelle": "github", "url": asset.get("browser_download_url"),
                      "name": asset["name"], "groesse": asset.get("size")}
    if not bester:
        return None
    hinweise.sort(key=lambda h: version_tuple(h["version"]), reverse=True)
    bester["hinweise"] = hinweise
    bester["notizen"] = "\n\n".join(f"{h['version']}\n{h['text']}" for h in hinweise)[:4000]
    return bester


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
            if rel.startswith(("/", "\\")) or ".." in rel.split("/") or ":" in rel.split("/")[0]:
                raise ValueError(f"Unsicherer Pfad im Zip: {info.filename}")
            ziel = (ziel_neu / rel).resolve()
            if ziel != ziel_neu.resolve() and ziel_neu.resolve() not in ziel.parents:
                raise ValueError(f"Unsicherer Pfad im Zip: {info.filename}")
            if info.is_dir():
                ziel.mkdir(parents=True, exist_ok=True)
            else:
                ziel.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as q, open(ziel, "wb") as f:
                    f.write(q.read())
    return ziel_neu


def tausch_skript_schreiben(app, neu, pid, starter):
    """Skript, das nach dem Ende dieses Prozesses den Ordner tauscht und neu startet.
    Windows: PowerShell ohne Fenster (Wait-Process) — eine Batch-Schleife mit tasklist/find öffnet
    ohne Konsole eigene Fenster und bleibt hängen."""
    app, neu = Path(app), Path(neu)
    alt = app.with_name(app.name + ".alt")
    log = app.parent / "update.log"
    if sys.platform == "win32":
        pfad = app.parent / "update.ps1"
        q = lambda p: str(p).replace("'", "''")       # PowerShell: ' in '…' verdoppeln (z. B. «O'Brien»)
        app, neu, alt, log, starter = q(app), q(neu), q(alt), q(log), q(starter)
        pfad.write_text("\r\n".join([
            "$ErrorActionPreference = 'Continue'",
            f"$log = '{log}'",
            "function Log($t) { Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $t) }",
            f"Log 'Update: warte auf Prozess {pid}'",
            f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue",
            "Start-Sleep -Seconds 1",
            f"if (Test-Path '{alt}') {{ Remove-Item -Recurse -Force '{alt}' }}",
            "$ok = $false",
            "for ($i = 0; $i -lt 30; $i++) {",
            f"  try {{ Move-Item -Path '{app}' -Destination '{alt}' -ErrorAction Stop; $ok = $true; break }} catch {{ Start-Sleep -Seconds 1 }}",
            "}",
            f"if (-not $ok) {{ Log 'Programmordner ist noch belegt — Update abgebrochen, alte Version bleibt.'; exit 1 }}",
            f"Move-Item -Path '{neu}' -Destination '{app}'",
            f"Remove-Item -Recurse -Force '{alt}' -ErrorAction SilentlyContinue",
            "Log 'Update: Ordner getauscht, starte neu'",
            f"Start-Process -FilePath '{starter}' -WorkingDirectory '{app}'",
            "Remove-Item -Force $PSCommandPath -ErrorAction SilentlyContinue",
        ]) + "\r\n", encoding="utf-8-sig")
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


def installieren(kandidat, konfig_dir, updates_dir=None, repo=GITHUB_REPO):
    """Zip beschaffen, prüfen, neben den App-Ordner entpacken und das Tausch-Skript starten.
    Der Aufrufer nennt nur Version und Quelle; URL bzw. Pfad werden serverseitig frisch ermittelt
    (nichts aus dem Browser wird heruntergeladen oder ausgeführt). Liefert den Pfad des Skripts."""
    app = app_ordner()
    if ist_entwicklung(app):
        raise RuntimeError("Dies ist ein Entwicklungs-Checkout (Git) — Update bitte mit «git pull».")
    gewuenscht = {"version": str(kandidat.get("version") or ""), "quelle": kandidat.get("quelle")}
    frisch = pruefe_github(repo) if gewuenscht["quelle"] == "github" else (pruefe_ordner(updates_dir) if updates_dir else None)
    if not frisch or frisch["version"] != gewuenscht["version"] or not ist_neuer(frisch["version"]):
        raise RuntimeError("Das angebotene Update ist nicht mehr verfügbar — bitte nochmals «Nach Update suchen».")
    kandidat = frisch
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
        # eigener, unsichtbarer Prozess, der den Server überlebt (CREATE_NO_WINDOW + eigene Prozessgruppe)
        flags = 0x08000000 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(skript)],
                         creationflags=flags, close_fds=True, cwd=str(app.parent),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["/bin/sh", str(skript)], start_new_session=True, close_fds=True)
    return skript
