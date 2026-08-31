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


from cockpit.model import build_mitglieder, status, Mitglied

def _mitglieder():
    return build_mitglieder([classify(h) for h in _helpers()])

def test_aggregation_ueber_fg():
    m = {x.fg: x for x in _mitglieder()}
    assert set(m) == {"FG-2417", "FG-1083", "FG-3105"}   # 108 ohne FG, 106/4812 ohne Mitglied
    assert m["FG-2417"].ist == 2.0        # 0 (Mitglied) + 2 (Zweitaccount 101) + 0 (109)
    assert m["FG-2417"].soll == 2.0       # nur vom Mitglieds-Account
    assert len(m["FG-2417"].accounts) == 3
    assert m["FG-1083"].ist == 1.0 and m["FG-1083"].soll == 2.0  # Zweitaccount-Zielwert 2 zählt NICHT

def test_soll_konflikt_bei_doppeltem_mitgliedsaccount():
    accounts = [classify(h) for h in _helpers()]
    doppel = classify(_helpers()[0])      # zweiter Mitglieds-Account FG-2417
    doppel.id = 999
    doppel.zielwert = 4.0
    ms = {x.fg: x for x in build_mitglieder(accounts + [doppel])}
    assert ms["FG-2417"].soll == 4.0      # max()
    assert ms["FG-2417"].soll_konflikt is True

def test_status_saison_und_halbjahr():
    m = {x.fg: x for x in _mitglieder()}
    assert status(m["FG-2417"], "saison", 1) == "erfuellt"
    assert status(m["FG-1083"], "saison", 1) == "auf_kurs"
    assert status(m["FG-3105"], "saison", 1) == "saeumig"
    assert status(m["FG-1083"], "halbjahr", 1) == "erfuellt"
    assert status(m["FG-3105"], "halbjahr", 1) == "saeumig"
