import datetime
import pytest
from cockpit.abgleich import gleiche_ab
from cockpit.fairgate_reader import FgKontakt
from cockpit.model import classify
from cockpit.settings import Regeln, KategorieRegel

REGELN = Regeln(kategorien=[KategorieRegel("Aktivmitglied", True, 2, "Mitglied"),
                            KategorieRegel("Junioren", True, 2, "Mitglied"),
                            KategorieRegel("Passivmitglied", False, 0, "")])
HEUTE = datetime.date(2026, 8, 31)

def _acc(id, vn, nn, mail, fg, gruppen=("Mitglied",), ziel=2.0):
    return classify({"id": id, "firstName": vn, "lastName": nn, "email": mail,
                     "adminRemarks": fg or "", "groups": [{"id": 1, "name": g} for g in gruppen],
                     "stateCache": {"requestedValue": ziel, "plannedValue": 0}})

def _kontakt(nr, vn, nn, mail="", kategorie="Junioren", geb="2012-01-01", eltern="eltern@example.ch"):
    return FgKontakt(fg=f"FG-{nr}", vorname=vn, nachname=nn, email=mail, telefon="",
                     geburtsdatum=geb, kategorie=kategorie, eltern_email=eltern)

def test_neueintritt_mit_eltern_mail_und_zielwert():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind")], [_acc(1, "Alt", "Da", "a@example.ch", "FG-1")], REGELN, HEUTE)
    assert len(e.neueintritte) == 1
    z = e.neueintritte[0]
    assert z.email == "eltern@example.ch"        # unter 16 → Eltern-Mail
    assert z.zielwert == "2" and z.bemerkungen == "FG-9" and z.gruppe == "Mitglied"

def test_neueintritt_ohne_mail_auf_klaerliste():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind", eltern="")], [], REGELN, HEUTE)
    assert e.neueintritte == [] and len(e.klaerliste) == 1

def test_nicht_pflichtige_kategorie_wird_ignoriert():
    e = gleiche_ab([_kontakt(9, "P", "Passiv", kategorie="Passivmitglied")], [], REGELN, HEUTE)
    assert e.neueintritte == [] and e.klaerliste == []

def test_austritt_auf_handarbeitsliste():
    e = gleiche_ab([], [_acc(1, "Weg", "Gezogen", "w@example.ch", "FG-1")], REGELN, HEUTE)
    assert len(e.handarbeit) == 1 and e.handarbeit[0].art == "austritt"

def test_schluessel_aenderung_bei_neuer_mail():
    konto = _acc(1, "Lina", "Brunner", "alt@example.ch", "FG-1")
    k = _kontakt(1, "Lina", "Brunner", mail="neu@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert len(e.handarbeit) == 1 and e.handarbeit[0].art == "schluessel"

def test_duplikat_waechter_case_insensitiv():
    konto = _acc(1, "Lina", "Brunner", "lina@example.ch", None)  # Portal ohne FG
    k = _kontakt(9, "lina", "brunner", mail="lina@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert e.neueintritte == [] and len(e.duplikat_warnungen) == 1

def test_zielwert_korrektur_fuer_zweitaccount():
    zweit = _acc(2, "Rita", "Gerber", "r@example.ch", "FG-1", gruppen=("Freiwillige",), ziel=2.0)
    haupt = _acc(1, "Lina", "Brunner", "l@example.ch", "FG-1")
    e = gleiche_ab([_kontakt(1, "Lina", "Brunner", mail="l@example.ch", geb="2000-01-01")],
                   [haupt, zweit], REGELN, HEUTE)
    korr = [z for z in e.korrekturen if z.vorname == "Rita"]
    assert len(korr) == 1 and korr[0].zielwert == "0" and korr[0].gruppe == ""

def test_sicherheitsstopp_ohne_fg_nummern():
    accounts = [_acc(i, f"A{i}", "B", f"{i}@example.ch", None) for i in range(10)]
    with pytest.raises(ValueError):
        gleiche_ab([_kontakt(1, "X", "Y")], accounts, REGELN, HEUTE)
