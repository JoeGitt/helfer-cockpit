"""Regeln: personendatenfreies JSON (Kategorien, Altersgrenze, Halbjahresziel)."""
import json
import os
from dataclasses import dataclass, asdict
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
    email_abweichung: str = "info"     # "info": nur auflisten | "handarbeit": als Schlüssel-Änderung führen
    aufbewahrung_tage: int = 90        # Ausgabedateien älter als so viele Tage werden gelöscht (0 = nie)

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


def lade_regeln_mit_fehler(pfad):
    """Wie lade_regeln, liefert aber zusätzlich einen Warnhinweis (leerer String bei Erfolg).

    Eine korrupte oder unerwartet strukturierte regeln.json darf das Cockpit nie zum Absturz
    bringen — bei jedem Lesefehler kommen die eingebauten Standardregeln zurück, verbunden mit
    einem für die Oberfläche sichtbaren Hinweis, statt eines stillen Fallbacks.
    """
    pfad = Path(pfad)
    if not pfad.exists():
        return _standard(), ""
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        regeln = Regeln(
            kategorien=[KategorieRegel(**k) for k in daten.get("kategorien", [])],
            altersgrenze=int(daten.get("altersgrenze", 16)),
            halbjahresziel=int(daten.get("halbjahresziel", 1)),
            email_abweichung=(daten.get("email_abweichung") or "info"),
            aufbewahrung_tage=max(0, int(daten.get("aufbewahrung_tage", 90))),
        )
        if regeln.email_abweichung not in ("info", "handarbeit"):
            raise ValueError("email_abweichung muss «info» oder «handarbeit» sein")
        return regeln, ""
    except (json.JSONDecodeError, TypeError, KeyError, ValueError, AttributeError) as e:
        return _standard(), (
            "Regeln-Datei (%s) ist beschädigt oder unerwartet strukturiert (%s) — "
            "Standardregeln werden verwendet, bitte in den Einstellungen neu speichern."
            % (pfad.name, e))


def lade_regeln(pfad):
    regeln, _fehler = lade_regeln_mit_fehler(pfad)
    return regeln


def speichere_regeln(regeln, pfad):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(regeln), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, pfad)
