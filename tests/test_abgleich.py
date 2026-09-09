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

def test_schluessel_aenderung_bei_neuer_mail_mit_strenger_regel():
    # Standard-Regel ist «info» (Abweichung nur auflisten) — die strenge Regel führt sie als Handarbeit.
    konto = _acc(1, "Lina", "Brunner", "alt@example.ch", "FG-1")
    k = _kontakt(1, "Lina", "Brunner", mail="neu@example.ch", geb="2000-01-01")
    streng = Regeln(kategorien=REGELN.kategorien, email_abweichung="handarbeit")
    e = gleiche_ab([k], [konto], streng, HEUTE)
    assert len(e.handarbeit) == 1 and e.handarbeit[0].art == "schluessel"

def test_duplikat_waechter_case_insensitiv():
    konto = _acc(1, "Lina", "Brunner", "lina@example.ch", None)  # Portal ohne FG
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = _kontakt(9, "lina", "brunner", mail="lina@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and len(e.duplikat_warnungen) == 1

def test_zielwert_korrektur_fuer_zweitaccount():
    zweit = _acc(2, "Rita", "Gerber", "r@example.ch", "FG-1", gruppen=("Freiwillige",), ziel=2.0)
    haupt = _acc(1, "Lina", "Brunner", "l@example.ch", "FG-1")
    e = gleiche_ab([_kontakt(1, "Lina", "Brunner", mail="l@example.ch", geb="2000-01-01")],
                   [haupt, zweit], REGELN, HEUTE)
    korr = [z for z in e.korrekturen if z.vorname == "Rita"]
    assert len(korr) == 1 and korr[0].zielwert == "0" and korr[0].gruppe == ""

def test_feld_leerung_wenn_fairgate_telefon_geleert():
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "l@example.ch",
                      "phone": "079 111 22 33", "adminRemarks": "FG-1",
                      "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 2.0, "plannedValue": 0}})
    k = _kontakt(1, "Lina", "Brunner", mail="l@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    leerungen = [h for h in e.handarbeit if h.art == "leerung"]
    assert len(leerungen) == 1 and "Telefon" in leerungen[0].detail


def test_fg_nachtrag_bei_leerer_bemerkung_wird_korrektur():
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "lina@example.ch",
                      "adminRemarks": "", "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")  # haelt Sicherheitsstopp ab
    k = FgKontakt(fg="FG-7", vorname="Lina", nachname="Brunner", email="lina@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and e.duplikat_warnungen == [] and e.klaerliste == []
    korr = [z for z in e.korrekturen if z.vorname == "Lina"]
    assert len(korr) == 1
    assert korr[0].nachname == "Brunner" and korr[0].email == "lina@example.ch"
    assert korr[0].bemerkungen == "FG-7" and korr[0].zielwert == "2" and korr[0].gruppe == ""

def test_fg_nachtrag_bei_belegter_bemerkung_auf_klaerliste():
    konto = classify({"id": 1, "firstName": "Noah", "lastName": "Keller", "email": "noah@example.ch",
                      "adminRemarks": "Zahlt bar", "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")  # haelt Sicherheitsstopp ab
    k = FgKontakt(fg="FG-8", vorname="Noah", nachname="Keller", email="noah@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and e.duplikat_warnungen == [] and e.korrekturen == []
    assert len(e.klaerliste) == 1
    assert "Bemerkungsfeld" in e.klaerliste[0]

def test_sicherheitsstopp_ohne_fg_nummern():
    accounts = [_acc(i, f"A{i}", "B", f"{i}@example.ch", None) for i in range(10)]
    with pytest.raises(ValueError):
        gleiche_ab([_kontakt(1, "X", "Y")], accounts, REGELN, HEUTE)


# ---- C1: Korrektur-Zeilen dürfen adminRemarks nie überschreiben ----------

def test_wert_korrektur_ueberschreibt_bemerkungen_nicht():
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "l@example.ch",
                      "phone": "079 111 22 33", "adminRemarks": "Zahlt bar, Trainerin, FG-1",
                      "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    k = _kontakt(1, "Lina", "Brunner", mail="l@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    korr = [z for z in e.korrekturen if z.vorname == "Lina"]
    assert len(korr) == 1 and korr[0].bemerkungen == ""


def test_zweitaccount_null_korrektur_ueberschreibt_bemerkungen_nicht():
    haupt = _acc(1, "Lina", "Brunner", "l@example.ch", "FG-1")
    frei = classify({"id": 2, "firstName": "Rita", "lastName": "Gerber", "email": "r@example.ch",
                     "adminRemarks": "Zahlt bar, Trainerin, FG-1",
                     "groups": [{"id": 1, "name": "Freiwillige"}],
                     "stateCache": {"requestedValue": 2.0, "plannedValue": 0}})
    e = gleiche_ab([_kontakt(1, "Lina", "Brunner", mail="l@example.ch", geb="2000-01-01")],
                   [haupt, frei], REGELN, HEUTE)
    korr = [z for z in e.korrekturen if z.vorname == "Rita"]
    assert len(korr) == 1 and korr[0].bemerkungen == ""


def test_fg_nachtrag_bei_leerer_bemerkung_behaelt_fg_als_bemerkung():
    # D4-Zweig bleibt unverändert: hier IST das Schreiben der Zweck.
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "lina@example.ch",
                      "adminRemarks": "", "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = FgKontakt(fg="FG-7", vorname="Lina", nachname="Brunner", email="lina@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    korr = [z for z in e.korrekturen if z.vorname == "Lina"]
    assert len(korr) == 1 and korr[0].bemerkungen == "FG-7"


# ---- I2: Unbekannte Fairgate-Kategorien warnen statt still Austritte -----

def test_unbekannte_kategorie_erzeugt_warnung_kein_austritt_kein_neueintritt():
    konto = _acc(1, "Weg", "Gezogen", "w@example.ch", "FG-1")
    k = _kontakt(1, "Weg", "Gezogen", mail="w@example.ch", kategorie="Vereinsfremd", geb="2000-01-01")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert e.neueintritte == []
    assert not any(h.art == "austritt" for h in e.handarbeit)
    assert len(e.unbekannte_kategorien) == 1
    assert "Vereinsfremd" in e.unbekannte_kategorien[0]
    assert "1 Kontakten" in e.unbekannte_kategorien[0]


def test_bekannte_nicht_pflichtige_kategorie_erzeugt_keine_warnung():
    e = gleiche_ab([_kontakt(9, "P", "Passiv", kategorie="Passivmitglied")], [], REGELN, HEUTE)
    assert e.unbekannte_kategorien == []


def test_unbekannte_kategorie_neueintritt_wird_nicht_angelegt():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind", kategorie="Vereinsfremd")], [], REGELN, HEUTE)
    assert e.neueintritte == [] and len(e.unbekannte_kategorien) == 1


# ---- I6: FG-Nachtrag nur für Mitglieds-Accounts + Namens-Warnung ---------

def test_fg_nachtrag_ignoriert_nicht_mitglieds_accounts():
    # Konto ohne FG, aber Typ Freiwillig (nicht Mitglied) — kein automatischer FG-Nachtrag.
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "lina@example.ch",
                      "adminRemarks": "", "groups": [{"id": 1, "name": "Freiwillige"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = FgKontakt(fg="FG-7", vorname="Lina", nachname="Brunner", email="lina@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.korrekturen == []
    assert len(e.duplikat_warnungen) == 1
    assert "namensgleicher" in e.duplikat_warnungen[0].lower()


def test_namensgleicher_account_ohne_fg_wird_gewarnt_nicht_importiert():
    konto = classify({"id": 1, "firstName": "Noah", "lastName": "Keller", "email": "alt@example.ch",
                      "adminRemarks": "", "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = FgKontakt(fg="FG-8", vorname="Noah", nachname="Keller", email="neu@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and e.korrekturen == [] and e.klaerliste == []
    assert len(e.duplikat_warnungen) == 1
    assert "Noah Keller" in e.duplikat_warnungen[0]


# ---- Minor: Geburtsdatum auch DD.MM.YYYY, unparseable -> Klärliste ------

def test_geburtsdatum_deutsches_format_wird_erkannt():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind", geb="01.04.2012")], [], REGELN, HEUTE)
    assert len(e.neueintritte) == 1
    assert e.neueintritte[0].email == "eltern@example.ch"   # unter 16 -> Eltern-Mail


def test_geburtsdatum_unparsebar_landet_auf_klaerliste():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind", geb="nicht-lesbar")], [], REGELN, HEUTE)
    assert e.neueintritte == []
    assert len(e.klaerliste) == 1
    assert "Geburtsdatum" in e.klaerliste[0]


def test_geburtsdatum_unparsebar_loest_keinen_austritt_aus():
    # Mitglied bleibt trotz kaputtem Geburtsdatum als "in Fairgate vorhanden" gezählt.
    konto = _acc(1, "Alt", "Konto", "alt@example.ch", "FG-1")
    k = _kontakt(1, "Alt", "Konto", mail="alt@example.ch", geb="kaputt")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert not any(h.art == "austritt" for h in e.handarbeit)


# ---- Minor: Duplikat-Wächter-Set um zusatz_email1/2 erweitert -----------

def test_duplikat_waechter_beruecksichtigt_zusatz_email():
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "primaer@example.ch",
                      "additionalEmail1": "lina@example.ch", "adminRemarks": "",
                      "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = _kontakt(9, "lina", "brunner", mail="lina@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and len(e.duplikat_warnungen) == 1


# ---------------------------------------------------------------------------
# E-Mail-Toleranz, FG-Nachtrag für Unklassifizierte, Kategorien-Übersicht, helper_id
# ---------------------------------------------------------------------------

def _kontakt_mails(nr, vn, nn, eigene, eltern, geb="2000-01-01"):
    k = _kontakt(nr, vn, nn, mail=eigene, geb=geb, eltern=eltern)
    k.alle_emails = [m for m in (eigene, eltern) if m]
    return k

def test_portal_auf_elternmail_ist_keine_schluesselaenderung():
    konto = _acc(1, "Lina", "Brunner", "eltern@example.ch", "FG-1")          # Portal läuft auf Eltern-Mail
    k = _kontakt_mails(1, "Lina", "Brunner", "lina@example.ch", "eltern@example.ch")  # erwachsen
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert e.handarbeit == [] and e.kontakt_abweichungen == []

def test_gross_kleinschreibung_ist_keine_abweichung():
    konto = _acc(1, "Lina", "Brunner", "Lina@Example.ch", "FG-1")
    k = _kontakt_mails(1, "Lina", "Brunner", "lina@example.ch", "")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert e.handarbeit == [] and e.kontakt_abweichungen == []

def test_echte_abweichung_wird_info_oder_handarbeit_je_nach_regel():
    konto = _acc(1, "Lina", "Brunner", "alt@example.ch", "FG-1")
    k = _kontakt_mails(1, "Lina", "Brunner", "neu@example.ch", "")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)                        # Standard: info
    assert e.handarbeit == []
    assert len(e.kontakt_abweichungen) == 1
    ab = e.kontakt_abweichungen[0]
    assert ab["fg"] == "FG-1" and ab["portal_mail"] == "alt@example.ch" and ab["fairgate_mail"] == "neu@example.ch"
    assert ab["helper_id"] == 1
    streng = Regeln(kategorien=REGELN.kategorien, email_abweichung="handarbeit")
    e2 = gleiche_ab([k], [konto], streng, HEUTE)
    assert len(e2.handarbeit) == 1 and e2.handarbeit[0].art == "schluessel" and e2.handarbeit[0].helper_id == 1
    assert e2.kontakt_abweichungen == []

def test_fg_nachtrag_fuer_unklassifizierten_account_mit_gruppen_merge():
    unklass = _acc(5, "Neu", "Kind", "neu@example.ch", None, gruppen=("Foodbox", "Infrastrukur"), ziel=2.0)
    k = _kontakt_mails(9, "Neu", "Kind", "neu@example.ch", "", geb="2000-01-01")
    e = gleiche_ab([k], [unklass], REGELN, HEUTE)
    assert e.neueintritte == [] and e.duplikat_warnungen == []
    assert len(e.korrekturen) == 1
    z = e.korrekturen[0]
    assert z.bemerkungen == "FG-9" and z.zielwert == "2"
    assert set(z.gruppe.split(", ")) == {"Foodbox", "Infrastrukur", "Mitglied"}   # Vereinigung, nie Ersatz

def test_austritt_traegt_helper_id():
    e = gleiche_ab([], [_acc(7, "Weg", "Gezogen", "w@example.ch", "FG-1")], REGELN, HEUTE)
    assert e.handarbeit[0].art == "austritt" and e.handarbeit[0].helper_id == 7

def test_kategorien_uebersicht():
    ks = [_kontakt(1, "A", "B", kategorie="Aktivmitglied"), _kontakt(2, "C", "D", kategorie="Aktivmitglied"),
          _kontakt(3, "E", "F", kategorie="Passivmitglied"), _kontakt(4, "G", "H", kategorie="Gönner")]
    e = gleiche_ab(ks, [], REGELN, HEUTE)
    assert e.kategorien == {"pflichtig": {"Aktivmitglied": 2}, "nicht_pflichtig": {"Passivmitglied": 1},
                            "unbekannt": {"Gönner": 1}}
