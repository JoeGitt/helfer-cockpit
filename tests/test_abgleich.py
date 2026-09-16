import datetime
import pytest
from cockpit.abgleich import gleiche_ab

def _kt(kf):
    """Klärfall (dict) als durchsuchbarer Text."""
    return kf if isinstance(kf, str) else " ".join([kf["titel"]] + kf["fakten"] + kf["optionen"])
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

def test_exakter_treffer_case_insensitiv_wird_fg_nachtrag():
    # Portal-Mitglied ohne FG, in Fairgate mit gleicher Mail und (anders geschriebenem) Namen:
    # das IST das Mitglied → FG per Import nachtragen, kein Neueintritt, keine Warnung.
    konto = _acc(1, "Lina", "Brunner", "lina@example.ch", None)
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = _kontakt(9, "lina", "brunner", mail="lina@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and e.duplikat_warnungen == [] and e.klaerliste == []
    z = next(z for z in e.korrekturen if z.vorname == "Lina")
    assert z.bemerkungen == "FG-9" and z.email == "lina@example.ch"      # Portal-Schreibweise als Schlüssel

def test_zielwert_korrektur_fuer_zweitaccount():
    zweit = _acc(2, "Rita", "Gerber", "r@example.ch", "FG-1", gruppen=("Freiwillige",), ziel=2.0)
    haupt = _acc(1, "Lina", "Brunner", "l@example.ch", "FG-1")
    e = gleiche_ab([_kontakt(1, "Lina", "Brunner", mail="l@example.ch", geb="2000-01-01")],
                   [haupt, zweit], REGELN, HEUTE)
    korr = [z for z in e.korrekturen if z.vorname == "Rita"]
    assert len(korr) == 1 and korr[0].zielwert == "0" and korr[0].gruppe == ""


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
    assert "Bemerkungsfeld" in _kt(e.klaerliste[0])

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

def test_freiwilliger_mit_exaktem_treffer_wird_mitglied():
    # Freiwilligen-Account, der in Fairgate ein pflichtiges Mitglied ist und noch keinen
    # Mitglieds-Account hat → wird per Import zum Mitglied (FG, Gruppe, Zielwert).
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "lina@example.ch",
                      "adminRemarks": "", "groups": [{"id": 1, "name": "Freiwillige"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = FgKontakt(fg="FG-7", vorname="Lina", nachname="Brunner", email="lina@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    z = next(z for z in e.korrekturen if z.vorname == "Lina")
    assert z.bemerkungen == "FG-7" and z.zielwert == "2" and z.gruppe == "Mitglied"
    assert e.neueintritte == [] and e.duplikat_warnungen == []


def test_namensgleicher_account_ohne_fg_wird_klaerfall_nicht_importiert():
    konto = classify({"id": 1, "firstName": "Noah", "lastName": "Keller", "email": "alt@example.ch",
                      "adminRemarks": "", "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = FgKontakt(fg="FG-8", vorname="Noah", nachname="Keller", email="neu@example.ch",
                 telefon="", geburtsdatum="2000-01-01", kategorie="Aktivmitglied", eltern_email="")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and not any(z.vorname == "Noah" for z in e.korrekturen)
    assert len(e.klaerliste) == 1 and "Noah Keller" in _kt(e.klaerliste[0]) and "FG-8" in _kt(e.klaerliste[0])


# ---- Minor: Geburtsdatum auch DD.MM.YYYY, unparseable -> Klärliste ------

def test_geburtsdatum_deutsches_format_wird_erkannt():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind", geb="01.04.2012")], [], REGELN, HEUTE)
    assert len(e.neueintritte) == 1
    assert e.neueintritte[0].email == "eltern@example.ch"   # unter 16 -> Eltern-Mail


def test_geburtsdatum_unparsebar_landet_auf_klaerliste():
    e = gleiche_ab([_kontakt(9, "Neu", "Kind", geb="nicht-lesbar")], [], REGELN, HEUTE)
    assert e.neueintritte == []
    assert len(e.klaerliste) == 1
    assert "Geburtsdatum" in _kt(e.klaerliste[0]) and e.klaerliste[0]["wo"] == "Fairgate"


def test_geburtsdatum_unparsebar_loest_keinen_austritt_aus():
    # Mitglied bleibt trotz kaputtem Geburtsdatum als "in Fairgate vorhanden" gezählt.
    konto = _acc(1, "Alt", "Konto", "alt@example.ch", "FG-1")
    k = _kontakt(1, "Alt", "Konto", mail="alt@example.ch", geb="kaputt")
    e = gleiche_ab([k], [konto], REGELN, HEUTE)
    assert not any(h.art == "austritt" for h in e.handarbeit)


# ---- Minor: Duplikat-Wächter-Set um zusatz_email1/2 erweitert -----------

def test_zusatz_email_zaehlt_als_exakter_treffer():
    konto = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "primaer@example.ch",
                      "additionalEmail1": "lina@example.ch", "adminRemarks": "",
                      "groups": [{"id": 1, "name": "Mitglied"}],
                      "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    mit_fg = _acc(3, "Andere", "Person", "andere@example.ch", "FG-3")
    k = _kontakt(9, "lina", "brunner", mail="lina@example.ch", geb="2000-01-01")
    e = gleiche_ab([k], [konto, mit_fg], REGELN, HEUTE)
    assert e.neueintritte == [] and e.duplikat_warnungen == []
    z = next(z for z in e.korrekturen if z.vorname == "Lina")
    assert z.bemerkungen == "FG-9" and z.email == "primaer@example.ch"


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
    unklass = _acc(5, "Neu", "Kind", "neu@example.ch", None, gruppen=("Foodbox", "Infrastrukur"), ziel=1.0)
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



# ---------------------------------------------------------------------------
# Soll-Zustands-Logik (Neufassung 10.09.2026): Fälle der Matrix aus den Kunstdaten
# ---------------------------------------------------------------------------

def _k_erw(nr, vn, nn, mail, kategorie="Aktivmitglied"):
    k = _kontakt(nr, vn, nn, mail=mail, kategorie=kategorie, geb="2000-01-01", eltern="")
    k.alle_emails = [mail] if mail else []
    return k

def test_fall_b_sieht_wie_mitglied_aus_ohne_fairgate_bezug_wird_freiwillig():
    # Gruppe «Mitglied» + «Freiwillige», Zielwert 2, keine FG, nirgends in Fairgate (dein Beispiel)
    a = _acc(1, "Karl", "Ohne", "karl@example.ch", None, gruppen=("Mitglied", "Freiwillige", "Foodbox"), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")], REGELN, HEUTE)
    z = next(z for z in e.korrekturen if z.vorname == "Karl")
    assert z.zielwert == "0" and set(z.gruppe.split(", ")) == {"Freiwillige", "Foodbox"}
    assert "Kein Mitglied in Fairgate" in z.grund
    assert e.klaerliste == []

def test_fall_b_mit_gleichem_nachnamen_wird_vorfrage_statt_import():
    a = _acc(1, "Reto", "Brunner", "reto@example.ch", None, gruppen=("Mitglied",), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")], REGELN, HEUTE)
    assert not any(z.vorname == "Reto" for z in e.korrekturen)          # erst fragen, dann importieren
    assert e.klaerliste == [] and e.hinweise == []
    assert len(e.vorfragen) == 1
    v = e.vorfragen[0]
    assert v["helper_id"] == 1 and v["name"] == "Reto Brunner"
    assert v["kandidaten"] == [{"fg": "FG-1", "name": "Lina Brunner", "telefon": "", "portal_account": "lina@example.ch"}]

def test_vorfrage_beantwortet_zweitaccount_erzeugt_importzeile_mit_fg():
    a = _acc(1, "Reto", "Brunner", "reto@example.ch", None, gruppen=("Mitglied", "Bar"), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")],
                   REGELN, HEUTE, entscheide={"1": {"antwort": "zweitaccount", "fg": "FG-1"}})
    assert e.vorfragen == [] and e.klaerliste == []
    z = next(z for z in e.korrekturen if z.vorname == "Reto")
    assert z.bemerkungen == "FG-1" and z.zielwert == "0" and set(z.gruppe.split(", ")) == {"Bar", "Freiwillige"}
    assert "deine Antwort" in z.grund and "Lina Brunner" in z.grund

def test_vorfrage_zweitaccount_mit_belegter_bemerkung_gibt_klaerfall():
    a = classify({"id": 1, "firstName": "Reto", "lastName": "Brunner", "email": "reto@example.ch",
                  "adminRemarks": "zahlt bar", "groups": [{"id": 1, "name": "Mitglied"}],
                  "stateCache": {"requestedValue": 2, "plannedValue": 0}})
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")],
                   REGELN, HEUTE, entscheide={"1": {"antwort": "zweitaccount", "fg": "FG-1"}})
    z = next(z for z in e.korrekturen if z.vorname == "Reto")
    assert z.bemerkungen == "" and z.zielwert == "0"                     # Import überschreibt keine Bemerkung
    assert len(e.klaerliste) == 1 and "belegt" in e.klaerliste[0]["titel"] and "zahlt bar" in _kt(e.klaerliste[0])

def test_vorfrage_beantwortet_andere_person_importiert_ohne_fg():
    a = _acc(1, "Reto", "Brunner", "reto@example.ch", None, gruppen=("Mitglied",), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")],
                   REGELN, HEUTE, entscheide={"1": {"antwort": "andere"}})
    z = next(z for z in e.korrekturen if z.vorname == "Reto")
    assert z.bemerkungen == "" and z.zielwert == "0" and "andere Person" in z.grund
    assert e.vorfragen == [] and e.klaerliste == []

def test_vorfrage_unklar_wird_klaerfall_mit_telefon_ohne_importzeile():
    a = _acc(1, "Reto", "Brunner", "reto@example.ch", None, gruppen=("Mitglied",), ziel=2.0)
    k = _k_erw(1, "Lina", "Brunner", "lina@example.ch"); k.telefon = "079 123 45 67"
    e = gleiche_ab([k], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")],
                   REGELN, HEUTE, entscheide={"1": {"antwort": "unklar"}})
    assert not any(z.vorname == "Reto" for z in e.korrekturen)
    assert len(e.klaerliste) == 1 and "079 123 45 67" in _kt(e.klaerliste[0])

def test_vorfrage_mit_fremder_fg_zaehlt_als_unbeantwortet():
    a = _acc(1, "Reto", "Brunner", "reto@example.ch", None, gruppen=("Mitglied",), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")],
                   REGELN, HEUTE, entscheide={"1": {"antwort": "zweitaccount", "fg": "FG-999"}})
    assert len(e.vorfragen) == 1 and e.korrekturen == []

def test_fall_c_nur_mail_passt_wird_klaerfall_mit_vorschlag():
    a = _acc(1, "Petra", "Odermatt", "familie@example.ch", None, gruppen=("Freiwillige",), ziel=0.0)
    e = gleiche_ab([_k_erw(5, "Jan", "Odermatt", "familie@example.ch")], [a], REGELN, HEUTE)
    assert e.neueintritte == [] and e.korrekturen == []
    kf = e.klaerliste[0]
    assert len(e.klaerliste) == 1 and "FG-5" in _kt(kf) and kf["wo"] == "Portal" and kf["helper_id"] == 1
    assert len(kf["optionen"]) == 2 and any("Elternteil" in o for o in kf["optionen"])

def test_fall_d_exakter_treffer_bei_bestehendem_mitgliedsaccount_wird_zweitaccount():
    haupt = _acc(1, "Lina", "Brunner", "lina@example.ch", "FG-1")
    zweit = _acc(2, "Lina", "Brunner", "lina@example.ch", None, gruppen=("Foodbox",), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [haupt, zweit], REGELN, HEUTE)
    z = next(z for z in e.korrekturen if z.email == "lina@example.ch" and z.bemerkungen == "FG-1")
    assert z.zielwert == "0" and set(z.gruppe.split(", ")) == {"Foodbox", "Freiwillige"}
    assert "Zweitaccount" in z.grund and e.neueintritte == []

def test_fall_f1_fg_ohne_mitglied_marker_ist_das_mitglied():
    a = _acc(1, "Lina", "Brunner", "lina@example.ch", "FG-1", gruppen=("Foodbox",), ziel=0.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a], REGELN, HEUTE)
    z = e.korrekturen[0]
    assert z.zielwert == "2" and set(z.gruppe.split(", ")) == {"Foodbox", "Mitglied"} and z.bemerkungen == ""
    assert e.neueintritte == [] and e.handarbeit == []

def test_fall_f2_zweitaccount_bekommt_freiwillige_marker_und_null():
    haupt = _acc(1, "Lina", "Brunner", "lina@example.ch", "FG-1")
    zweit = _acc(2, "Reto", "Brunner", "reto@example.ch", "FG-1", gruppen=("Foodbox",), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [haupt, zweit], REGELN, HEUTE)
    z = next(z for z in e.korrekturen if z.vorname == "Reto")
    assert z.zielwert == "0" and set(z.gruppe.split(", ")) == {"Foodbox", "Freiwillige"}

def test_fall_g_mitglied_und_freiwillige_gleichzeitig_wird_bereinigt():
    a = _acc(1, "Lina", "Brunner", "lina@example.ch", "FG-1", gruppen=("Mitglied", "Freiwillige"), ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a], REGELN, HEUTE)
    assert len(e.korrekturen) == 1 and e.korrekturen[0].gruppe == "Mitglied" and e.korrekturen[0].zielwert == ""

def test_fall_i_unbekannte_mit_einsaetzen_werden_freiwillige():
    mit = classify({"id": 1, "firstName": "Dario", "lastName": "Ackermann", "email": "d@example.ch",
                    "adminRemarks": "", "groups": [{"id": 4, "name": "Unbekannte"}, {"id": 9, "name": "Foodbox"}],
                    "stateCache": {"requestedValue": 0, "plannedValue": 2, "okAssignmentsNum": 2}})
    ohne = classify({"id": 2, "firstName": "Still", "lastName": "Wasser", "email": "s@example.ch",
                     "adminRemarks": "", "groups": [{"id": 4, "name": "Unbekannte"}],
                     "stateCache": {"requestedValue": 0, "plannedValue": 0}})
    e = gleiche_ab([], [mit, ohne], REGELN, HEUTE)
    assert len(e.korrekturen) == 1 and e.korrekturen[0].vorname == "Dario"
    assert set(e.korrekturen[0].gruppe.split(", ")) == {"Foodbox", "Freiwillige"}

def test_nicht_pflichtige_kategorie_setzt_zielwert_null():
    a = _acc(1, "Paul", "Passiv", "p@example.ch", "FG-1", ziel=2.0)
    e = gleiche_ab([_k_erw(1, "Paul", "Passiv", "p@example.ch", kategorie="Passivmitglied")], [a], REGELN, HEUTE)
    assert len(e.korrekturen) == 1 and e.korrekturen[0].zielwert == "0" and e.handarbeit == []

def test_austritt_mit_treffer_auf_andere_fg_gibt_hinweis():
    a = _acc(1, "Lina", "Brunner", "lina@example.ch", "FG-1")
    e = gleiche_ab([_k_erw(99, "Lina", "Brunner", "lina@example.ch")], [a], REGELN, HEUTE)
    h = next(h for h in e.handarbeit if h.art == "austritt")
    assert "FG-99" in h.detail and "geändert" in h.detail
    assert e.neueintritte == []          # Kontakt FG-99 ist über Name/Mail dem Account zugeordnet — kein Neueintritt

def test_bemerkung_belegt_verhindert_fg_nachtrag_und_gibt_klaerfall():
    a = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "lina@example.ch",
                  "adminRemarks": "Zahlt bar", "groups": [{"id": 1, "name": "Mitglied"}],
                  "stateCache": {"requestedValue": 2, "plannedValue": 0}})
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")],
                   [a, _acc(2, "Andere", "Person", "andere@example.ch", "FG-2")], REGELN, HEUTE)
    assert not any(z.vorname == "Lina" for z in e.korrekturen) and e.neueintritte == []
    assert len(e.klaerliste) == 1 and "belegt" in _kt(e.klaerliste[0])


def test_fall_c1_gleiche_mail_bei_bestehendem_mitgliedsaccount_ist_zweitaccount_automatisch():
    # Mutter (eigener Account, ohne FG, nicht «Freiwillige») nutzt die E-Mail, die in Fairgate beim
    # Sohn steht; der Sohn hat bereits seinen Mitglieds-Account mit FG → eindeutig Zweitaccount.
    sohn = _acc(1, "Jan", "Odermatt", "jan@example.ch", "FG-5")
    mutter = _acc(2, "Petra", "Odermatt", "familie@example.ch", None, gruppen=("Foodbox",), ziel=2.0)
    k = _kontakt(5, "Jan", "Odermatt", mail="jan@example.ch", eltern="familie@example.ch", geb="2000-01-01")
    k.alle_emails = ["jan@example.ch", "familie@example.ch"]
    e = gleiche_ab([k], [sohn, mutter], REGELN, HEUTE)
    z = next(z for z in e.korrekturen if z.vorname == "Petra")
    assert z.bemerkungen == "FG-5" and z.zielwert == "0" and set(z.gruppe.split(", ")) == {"Foodbox", "Freiwillige"}
    assert "Zweitaccount von FG-5" in z.grund and "Jan Odermatt" in z.grund
    assert e.klaerliste == [] and e.neueintritte == []

def test_telefon_nur_im_portal_ist_keine_massnahme():
    a = classify({"id": 1, "firstName": "Lina", "lastName": "Brunner", "email": "lina@example.ch", "phone": "+41790000000",
                  "adminRemarks": "FG-1", "groups": [{"id": 1, "name": "Mitglied"}], "stateCache": {"requestedValue": 2, "plannedValue": 0}})
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [a], REGELN, HEUTE)
    assert e.handarbeit == [] and e.korrekturen == []

# ---- 10.09.2026 abends: Löschen statt Deaktivieren, Fall E mit zwei Zweigen, Telefon ----

def test_austritt_nennt_offene_einsaetze_oder_keine():
    a = _acc(1, "Weg", "Gezogen", "w@example.ch", "FG-1")
    e = gleiche_ab([], [a], REGELN, HEUTE)
    assert "Keine offenen Einsätze" in e.handarbeit[0].detail and "deaktivier" not in e.handarbeit[0].detail
    b = classify({"id": 2, "firstName": "Noch", "lastName": "Aktiv", "email": "n@example.ch", "adminRemarks": "FG-2",
                  "groups": [{"id": 1, "name": "Mitglied"}], "stateCache": {"requestedValue": 2, "plannedValue": 1, "confirmedAssignmentsNum": 3}})
    e = gleiche_ab([], [b], REGELN, HEUTE)
    assert "3 offene Einsätze" in e.handarbeit[0].detail

def test_fall_e_mit_bestehendem_account_bietet_zweitaccount_und_ersatz_an():
    neu = _acc(1, "Lina", "Brunner", "mama.brunner@example.ch", None, gruppen=("Mitglied",), ziel=2.0)
    alt = _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")
    k = _k_erw(1, "Lina", "Brunner", "")
    k.telefon = "079 000 00 00"
    e = gleiche_ab([k], [neu, alt], REGELN, HEUTE)
    kf = e.klaerliste[0]
    t = _kt(kf)
    assert "—" not in " ".join(kf["fakten"]) and "keiner E-Mail" in t and "079 000 00 00" in t
    assert any(o.startswith("Zweitaccount") for o in kf["optionen"])
    assert any(o.startswith("Dieselbe Person") and "löschen" in o and "lina@example.ch" in o for o in kf["optionen"])
    assert all(o.count(" → ") == 1 for o in kf["optionen"])        # das Frontend trennt am ersten Pfeil
    assert not any(z.vorname == "Lina" and z.email == "mama.brunner@example.ch" for z in e.korrekturen)

def test_fall_e_erledigter_namensvetter_taucht_nicht_mehr_auf():
    # Gleicher Name, bereits Freiwillige(r) mit Zielwert 0, Mitglied hat eigenen Account → still
    nv = _acc(1, "Lina", "Brunner", "andere@example.ch", None, gruppen=("Freiwillige",), ziel=0.0)
    alt = _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1")
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [nv, alt], REGELN, HEUTE)
    assert e.klaerliste == [] and e.neueintritte == []

def test_fall_e_ohne_bestehenden_account_bleibt_klaerfall():
    nv = _acc(1, "Lina", "Brunner", "andere@example.ch", None, gruppen=("Freiwillige",), ziel=0.0)
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch")], [nv], REGELN, HEUTE)
    assert len(e.klaerliste) == 1 and e.neueintritte == []          # sonst entstünde ein Duplikat

def test_neueintritt_ohne_mail_nennt_telefon_zum_anrufen():
    k = _kontakt(9, "Neu", "Kind", eltern="")
    k.telefon = "052 111 22 33"
    e = gleiche_ab([k], [], REGELN, HEUTE)
    t = _kt(e.klaerliste[0])
    assert "052 111 22 33" in t and "Anrufen" in t

def test_vorfragen_nach_einsaetzen_sortiert_und_geschwister_als_kandidaten():
    ohne = _acc(1, "Reto", "Brunner", "reto@example.ch", None, gruppen=("Mitglied",), ziel=2.0)
    mit = classify({"id": 3, "firstName": "Urs", "lastName": "Brunner", "email": "urs@example.ch", "adminRemarks": "",
                    "groups": [{"id": 1, "name": "Mitglied"}], "stateCache": {"requestedValue": 2, "plannedValue": 0, "okAssignmentsNum": 4}})
    e = gleiche_ab([_k_erw(1, "Lina", "Brunner", "lina@example.ch"), _k_erw(4, "Eva", "Brunner", "eva@example.ch")],
                   [ohne, mit, _acc(2, "Lina", "Brunner", "lina@example.ch", "FG-1"), _acc(4, "Eva", "Brunner", "eva@example.ch", "FG-4")], REGELN, HEUTE)
    assert [v["name"] for v in e.vorfragen] == ["Urs Brunner", "Reto Brunner"]
    assert [k["fg"] for k in e.vorfragen[0]["kandidaten"]] == ["FG-1", "FG-4"]
