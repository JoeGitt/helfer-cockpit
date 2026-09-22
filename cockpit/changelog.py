"""Versionshinweise aus cockpit/CHANGELOG.md — eine Quelle für die Oberfläche und das GitHub-Release."""
import re
from pathlib import Path

DATEI = Path(__file__).resolve().parent / "CHANGELOG.md"
_KOPF = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*(?:—|-)?\s*(.*)$")


def lies(text=None):
    """Liste von {version, datum, punkte}, neueste zuerst (Reihenfolge wie in der Datei)."""
    if text is None:
        try:
            text = DATEI.read_text(encoding="utf-8")
        except OSError:
            return []
    eintraege, aktuell = [], None
    for zeile in text.splitlines():
        m = _KOPF.match(zeile.strip())
        if m:
            aktuell = {"version": m.group(1), "datum": m.group(2).strip(), "punkte": []}
            eintraege.append(aktuell)
        elif aktuell and zeile.strip().startswith("- "):
            aktuell["punkte"].append(zeile.strip()[2:].strip())
        elif aktuell and aktuell["punkte"] and zeile.startswith("  ") and zeile.strip():
            aktuell["punkte"][-1] += " " + zeile.strip()          # Fortsetzungszeile
    return eintraege


def abschnitt(version, eintraege=None):
    """Markdown-Text einer Version für das GitHub-Release, oder "" wenn sie fehlt."""
    for e in eintraege if eintraege is not None else lies():
        if e["version"] == version:
            return "\n".join(f"- {p}" for p in e["punkte"])
    return ""
