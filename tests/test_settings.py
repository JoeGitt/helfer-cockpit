from cockpit.settings import (Regeln, KategorieRegel, lade_regeln, lade_regeln_mit_fehler,
                              speichere_regeln)

def test_standardregeln_ohne_datei(tmp_path):
    r = lade_regeln(tmp_path / "gibtsnicht.json")
    assert r.altersgrenze == 16 and r.halbjahresziel == 1
    assert r.fuer_kategorie("Aktivmitglied").zielwert == 2
    assert r.fuer_kategorie("Passivmitglied") is None

def test_speichern_und_laden(tmp_path):
    pfad = tmp_path / "regeln.json"
    r = Regeln(kategorien=[KategorieRegel("Aktivmitglied", True, 4, "Mitglied")],
               altersgrenze=18, halbjahresziel=2)
    speichere_regeln(r, pfad)
    r2 = lade_regeln(pfad)
    assert r2.altersgrenze == 18 and r2.fuer_kategorie("Aktivmitglied").zielwert == 4


# ---- I5(a): korrupte regeln.json -> Standardregeln + Warnhinweis ---------

def test_korruptes_json_liefert_standardregeln_und_fehler(tmp_path):
    pfad = tmp_path / "regeln.json"
    pfad.write_text("{das ist kein json", encoding="utf-8")
    regeln, fehler = lade_regeln_mit_fehler(pfad)
    assert regeln.altersgrenze == 16 and regeln.fuer_kategorie("Aktivmitglied").zielwert == 2
    assert fehler


def test_lade_regeln_bleibt_robust_bei_korruptem_json(tmp_path):
    pfad = tmp_path / "regeln.json"
    pfad.write_text("[]", encoding="utf-8")   # kein dict -> TypeError bei .get()
    r = lade_regeln(pfad)
    assert r.altersgrenze == 16


def test_intaktes_json_liefert_keinen_fehler(tmp_path):
    pfad = tmp_path / "regeln.json"
    r = Regeln(kategorien=[KategorieRegel("Aktivmitglied", True, 4, "Mitglied")],
               altersgrenze=18, halbjahresziel=2)
    speichere_regeln(r, pfad)
    regeln, fehler = lade_regeln_mit_fehler(pfad)
    assert fehler == "" and regeln.altersgrenze == 18


# ---- I5(b): atomares Speichern ---------

def test_speichern_ist_atomar_keine_tmp_datei_bleibt_liegen(tmp_path):
    pfad = tmp_path / "regeln.json"
    r = Regeln(kategorien=[KategorieRegel("Aktivmitglied", True, 2, "Mitglied")])
    speichere_regeln(r, pfad)
    reste = list(tmp_path.glob("*.tmp"))
    assert reste == [] and pfad.exists()
