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


# ---- Familien (Spez 6.11, 16.09.2026): mehrere FG-Nummern in einer Bemerkung = Topf ----
from cockpit.model import normalize_fgs, Familie

def _h(id, vn, nn, remark, gruppen=("Mitglied",), ziel=2, ist=0):
    return {"id": id, "firstName": vn, "lastName": nn, "email": f"{vn.lower()}@example.ch", "adminRemarks": remark,
            "groups": [{"id": i, "name": g} for i, g in enumerate(gruppen)],
            "stateCache": {"requestedValue": ziel, "plannedValue": ist}}

def test_normalize_fgs_alle_nummern_in_reihenfolge_ohne_doppelte():
    assert normalize_fgs("FG-7065, FG-7096") == ["FG-7065", "FG-7096"]
    assert normalize_fgs("fg 7096 / FG-7065 / fg7096") == ["FG-7096", "FG-7065"]
    assert normalize_fgs("") == [] and normalize_fgs(None) == []

def test_elternaccount_mit_zwei_nummern_bildet_familie_mit_topf():
    accounts = [classify(h) for h in [
        _h(1, "Elias", "Wenger", "FG-1", ziel=2, ist=1),
        _h(2, "Sara", "Wenger", "FG-2", ziel=2, ist=0),
        _h(3, "Petra", "Wenger", "FG-1, FG-2", gruppen=("Freiwillige",), ziel=0, ist=2),
        _h(4, "Noah", "Keller", "FG-3", ziel=2, ist=2)]]
    ms = {m.fg: m for m in build_mitglieder(accounts)}
    fam = ms["FG-1"].familie
    assert fam is not None and fam is ms["FG-2"].familie and ms["FG-3"].familie is None
    assert fam.name == "Familie Wenger" and fam.fgs == ["FG-1", "FG-2"]
    assert fam.soll == 4 and fam.ist == 3                    # 1 + 0 + 2 (Elternaccount einmal gezählt)
    assert sorted(a.id for a in fam.accounts) == [1, 2, 3]
    assert ms["FG-1"].ist == 1 and ms["FG-2"].ist == 0        # eigene Accounts bleiben sichtbar
    assert status(ms["FG-1"], "saison", 1) == "auf_kurs" == status(ms["FG-2"], "saison", 1)
    assert status(ms["FG-2"], "halbjahr", 1) == "erfuellt"    # Topf 3 ≥ 2 × Halbjahresziel

def test_geschwister_ohne_elternaccount_ueber_zweite_nummer_beim_kind():
    accounts = [classify(h) for h in [
        _h(1, "Elias", "Wenger", "FG-1, FG-2", ziel=2, ist=4),
        _h(2, "Sara", "Wenger", "FG-2", ziel=2, ist=0)]]
    ms = {m.fg: m for m in build_mitglieder(accounts)}
    assert ms["FG-1"].fg == "FG-1" and accounts[0].typ.value == "mitglied"   # erste Nummer = eigene
    assert ms["FG-1"].familie.ist == 4 and ms["FG-1"].familie.soll == 4
    assert status(ms["FG-2"], "saison", 1) == "erfuellt"

def test_familie_mit_verschiedenen_nachnamen_und_nummer_ohne_mitglied():
    accounts = [classify(h) for h in [
        _h(1, "Elias", "Wenger", "FG-1"), _h(2, "Lea", "Meier", "FG-2"),
        _h(3, "Petra", "Wenger", "FG-1, FG-2, FG-9", gruppen=("Freiwillige",), ziel=0, ist=1)]]
    ms = {m.fg: m for m in build_mitglieder(accounts)}
    assert ms["FG-1"].familie.name == "Familie Wenger / Meier" and ms["FG-1"].familie.fgs == ["FG-1", "FG-2"]

def test_zweitaccount_mit_zwei_nummern_ohne_zweites_mitglied_zaehlt_beim_ersten():
    accounts = [classify(h) for h in [
        _h(1, "Elias", "Wenger", "FG-1", ziel=2, ist=0),
        _h(3, "Petra", "Wenger", "FG-1, FG-2", gruppen=("Freiwillige",), ziel=0, ist=2)]]
    ms = {m.fg: m for m in build_mitglieder(accounts)}
    assert ms["FG-1"].familie is None and ms["FG-1"].ist == 2 and len(ms["FG-1"].accounts) == 2
