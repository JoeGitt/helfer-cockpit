import datetime
from cockpit.aufraeumen import abgelaufene, aufraeumen

HEUTE = datetime.date(2026, 9, 16)

def _anlegen(d, namen):
    for n in namen:
        (d / n).write_text("x")

def test_nur_eigene_dateien_nach_datum_im_namen(tmp_path):
    _anlegen(tmp_path, ["import-2026-05-01.xlsx", "import-2026-05-01-begruendung.html", "handarbeitsliste-2026-05-01.html",
                        "kontaktdaten-abweichungen-2026-05-01.csv", "saeumige-saison-2026-05-01.csv", "gesamtexport-2026-05-01.xlsx",
                        "import-2026-09-01.xlsx", "entscheide.json", "regeln.json", "fremde-datei-2026-01-01.xlsx", "notizen.txt"])
    (tmp_path / "Updates").mkdir(); (tmp_path / "Updates" / "HelferCockpit-1.0.0-windows.zip").write_text("x")
    alt = [p.name for p in abgelaufene(tmp_path, 90, HEUTE)]
    assert alt == sorted(["import-2026-05-01.xlsx", "import-2026-05-01-begruendung.html", "handarbeitsliste-2026-05-01.html",
                          "kontaktdaten-abweichungen-2026-05-01.csv", "saeumige-saison-2026-05-01.csv", "gesamtexport-2026-05-01.xlsx"])
    geloescht = aufraeumen(tmp_path, 90, HEUTE)
    assert len(geloescht) == 6
    assert (tmp_path / "import-2026-09-01.xlsx").exists() and (tmp_path / "entscheide.json").exists()
    assert (tmp_path / "fremde-datei-2026-01-01.xlsx").exists() and (tmp_path / "Updates" / "HelferCockpit-1.0.0-windows.zip").exists()

def test_null_tage_heisst_nie_und_fehlender_ordner_ist_ok(tmp_path):
    _anlegen(tmp_path, ["import-2020-01-01.xlsx"])
    assert abgelaufene(tmp_path, 0, HEUTE) == [] and aufraeumen(tmp_path / "fehlt", 90, HEUTE) == []
    assert (tmp_path / "import-2020-01-01.xlsx").exists()

def test_frist_genau_am_rand(tmp_path):
    _anlegen(tmp_path, ["import-2026-06-18.xlsx", "import-2026-06-17.xlsx"])     # 90 bzw. 91 Tage vor HEUTE
    assert [p.name for p in abgelaufene(tmp_path, 90, HEUTE)] == ["import-2026-06-17.xlsx"]
