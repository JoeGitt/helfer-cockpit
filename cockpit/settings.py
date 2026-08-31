"""Regeln: personendatenfreies JSON (Kategorien, Altersgrenze, Halbjahresziel)."""
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class KategorieRegel:
    name: str
    pflichtig: bool
    zielwert: int
    portal_gruppe: str


@dataclass
class Regeln:
    kategorien: list
    altersgrenze: int = 16
    halbjahresziel: int = 1

    def fuer_kategorie(self, name):
        for k in self.kategorien:
            if k.name == name and k.pflichtig:
                return k
        return None


def _standard():
    return Regeln(kategorien=[
        KategorieRegel("Aktivmitglied", True, 2, "Mitglied"),
        KategorieRegel("Junioren", True, 2, "Mitglied"),
    ])


def lade_regeln(pfad):
    pfad = Path(pfad)
    if not pfad.exists():
        return _standard()
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    return Regeln(
        kategorien=[KategorieRegel(**k) for k in daten.get("kategorien", [])],
        altersgrenze=int(daten.get("altersgrenze", 16)),
        halbjahresziel=int(daten.get("halbjahresziel", 1)),
    )


def speichere_regeln(regeln, pfad):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(asdict(regeln), ensure_ascii=False, indent=2), encoding="utf-8")
