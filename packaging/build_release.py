#!/usr/bin/env python3
"""Windows-Paket bauen (läuft auf jedem System mit Internet):
  HelferCockpit-<version>-windows.zip  =  HelferCockpit/{python (eingebettet), lib (Abhängigkeiten),
                                          cockpit, start.py, Helfer-Cockpit.bat, VERSION.txt}
Kein Compiler, keine Signatur: reine Dateien. Der API-Key ist nie Teil des Pakets."""
import io
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
from cockpit.version import VERSION  # noqa: E402

PYTHON_VERSION = "3.12.10"
PYTHON_ZIP = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
ABHAENGIGKEITEN = ["openpyxl", "keyring", "pywin32-ctypes"]     # pywin32-ctypes: Schlüsselbund unter Windows
DIST = WURZEL / "dist"


def lade(url):
    print("lade", url)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main():
    ziel = DIST / "HelferCockpit"
    if ziel.exists():
        shutil.rmtree(ziel)
    ziel.mkdir(parents=True)
    # 1. eingebettetes Python
    py = ziel / "python"
    with zipfile.ZipFile(io.BytesIO(lade(PYTHON_ZIP))) as z:
        z.extractall(py)
    pth = next(py.glob("python*._pth"))
    pth.write_text("\n".join([pth.read_text().splitlines()[0], ".", "..\\lib", "..", "import site", ""]), encoding="utf-8")
    # 2. Abhängigkeiten als reine Python-Wheels für Windows
    lib = ziel / "lib"
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--target", str(lib),
                    "--platform", "win_amd64", "--python-version", PYTHON_VERSION.rsplit(".", 1)[0],
                    "--only-binary=:all:", "--upgrade", *ABHAENGIGKEITEN,
                    "et-xmlfile", "jaraco.classes", "jaraco.functools", "jaraco.context", "more-itertools", "backports.tarfile"],
                   check=True)
    for p in lib.glob("*.dist-info/RECORD"):
        pass
    # 3. Programm
    shutil.copytree(WURZEL / "cockpit", ziel / "cockpit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(WURZEL / "start.py", ziel / "start.py")
    shutil.copy2(WURZEL / "packaging" / "Helfer-Cockpit.bat", ziel / "Helfer-Cockpit.bat")
    shutil.copy2(WURZEL / "packaging" / "Helfer-Cockpit Konsole.bat", ziel / "Helfer-Cockpit Konsole.bat")
    fixtures = ziel / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    for name in ("helpers.json", "assignments.json"):      # fiktive Demo-Daten für --demo
        shutil.copy2(WURZEL / "tests" / "fixtures" / name, fixtures / name)
    (ziel / "VERSION.txt").write_text(VERSION + "\n", encoding="utf-8")
    shutil.copy2(WURZEL / "README.md", ziel / "README.md")
    # 4. Zip
    zip_pfad = DIST / f"HelferCockpit-{VERSION}-windows.zip"
    with zipfile.ZipFile(zip_pfad, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ziel.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(DIST).as_posix())
    print("fertig:", zip_pfad, f"{zip_pfad.stat().st_size / 1e6:.1f} MB")
    return zip_pfad


if __name__ == "__main__":
    main()
