"""Lauf-Protokoll: JSON-Zeilen, keine Personendaten."""
import json
import datetime
from pathlib import Path


def logge(pfad, aktion, zaehler):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    eintrag = {"zeit": datetime.datetime.now().isoformat(timespec="seconds"),
               "aktion": aktion, **zaehler}
    with pfad.open("a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def lese(pfad, max_eintraege=200):
    pfad = Path(pfad)
    if not pfad.exists():
        return []
    zeilen = pfad.read_text(encoding="utf-8").strip().splitlines()
    eintraege = []
    for z in reversed(zeilen[-max_eintraege:]):
        try:
            eintraege.append(json.loads(z))
        except json.JSONDecodeError:
            continue    # eine einzelne kaputte Zeile darf das restliche Protokoll nicht sperren
    return eintraege
