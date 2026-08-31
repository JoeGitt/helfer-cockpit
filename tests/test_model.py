import pytest
import json
from pathlib import Path
from cockpit.model import normalize_fg, classify, Typ

@pytest.mark.parametrize("text,erwartet", [
    ("FG-2417", ("FG-2417", False)),
    ("FG-2417 zweiter Account", ("FG-2417", False)),
    ("fg 2417", ("FG-2417", True)),            # Schreibweise abweichend
    ("fg-2417", ("FG-2417", True)),            # Kleinschreibung
    ("Zahlt bar, FG-2417 nachgetragen", ("FG-2417", True)),  # nicht am Anfang
    ("FG–2417", ("FG-2417", True)),            # Gedankenstrich
    ("", (None, False)),
    (None, (None, False)),
    ("Unbekannt, kein Vereinsbezug", (None, False)),
])
def test_normalize_fg(text, erwartet):
    assert normalize_fg(text) == erwartet

def test_normalize_fg_nimmt_ersten_treffer():
    assert normalize_fg("FG-1 und FG-2")[0] == "FG-1"


FIXTURES = Path(__file__).parent / "fixtures"

def _helpers():
    return json.loads((FIXTURES / "helpers.json").read_text(encoding="utf-8"))

def test_classify_typen():
    typen = {h["id"]: classify(h).typ for h in _helpers()}
    assert typen[100] == Typ.MITGLIED        # FG + Gruppe Mitglied
    assert typen[101] == Typ.ZWEITACCOUNT    # FG + Gruppe ohne Mitglied
    assert typen[104] == Typ.FREIWILLIG      # keine FG, Gruppe Freiwillige
    assert typen[105] == Typ.UNBEKANNT       # keine FG, Gruppe Unbekannte
    assert typen[108] == Typ.MITGLIED        # Gruppe Mitglied ohne FG bleibt Mitglied (Check D4 meldet)
    assert typen[109] == Typ.ZWEITACCOUNT    # nonstandard-FG mitten im Text

def test_classify_werte_und_zaehler():
    a = classify(_helpers()[1])  # id 101
    assert a.fg == "FG-2417" and a.zielwert == 0 and a.ist_wert == 2
    assert a.num_ok == 2 and a.num_nok == 0

def test_classify_unklassifiziert():
    h = _helpers()[0]
    h["groups"] = [{"id": 9, "name": "Foodbox"}]
    h["adminRemarks"] = ""
    assert classify(h).typ == Typ.UNKLASSIFIZIERT

def test_classify_gruppen_als_namen():
    a = classify(_helpers()[2])  # id 102
    assert a.gruppen == ["Mitglied", "Foodbox"]
