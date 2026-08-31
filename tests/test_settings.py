from cockpit.settings import Regeln, KategorieRegel, lade_regeln, speichere_regeln

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
