import json
import zipfile
from pathlib import Path
from cockpit import updater, standort
from cockpit.version import VERSION


def test_versionsvergleich():
    assert updater.ist_neuer("2.2.0", "2.1.9") and not updater.ist_neuer("2.1.0", "2.1.0")
    assert updater.version_tuple("v2.10.3") == (2, 10, 3) and updater.version_tuple("kaputt") == (0, 0, 0)


def test_update_ordner_findet_neueste_zip(tmp_path):
    (tmp_path / "HelferCockpit-2.0.0-windows.zip").write_bytes(b"x")
    (tmp_path / "HelferCockpit-9.9.9-windows.zip").write_bytes(b"x")
    (tmp_path / "irgendwas.zip").write_bytes(b"x")
    k = updater.pruefe_ordner(tmp_path)
    assert k["version"] == "9.9.9" and k["quelle"] == "ordner"
    assert updater.pruefe_ordner(tmp_path / "fehlt") is None


def test_pruefe_ohne_internet_nutzt_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "pruefe_github", lambda repo=None, timeout=8: None)
    (tmp_path / "HelferCockpit-9.9.9-windows.zip").write_bytes(b"x")
    d = updater.pruefe(tmp_path)
    assert d["aktuell"] == VERSION and d["neu"]["version"] == "9.9.9" and d["github_erreichbar"] is False
    (tmp_path / "HelferCockpit-9.9.9-windows.zip").unlink()
    assert updater.pruefe(tmp_path)["neu"] is None           # nichts Neueres → kein Update


def test_zip_pruefen_und_entpacken(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("HelferCockpit/cockpit/version.py", "VERSION='9.9.9'")
        f.writestr("HelferCockpit/start.py", "print(1)")
    assert updater.zip_pruefen(z) == "HelferCockpit"
    neu = updater.entpacken(z, tmp_path / "app.new")
    assert (neu / "cockpit" / "version.py").read_text() == "VERSION='9.9.9'" and (neu / "start.py").exists()
    kaputt = tmp_path / "k.zip"
    with zipfile.ZipFile(kaputt, "w") as f:
        f.writestr("x/y.txt", "nix")
    try:
        updater.zip_pruefen(kaputt); assert False
    except ValueError:
        pass


def test_tausch_skript_wartet_auf_pid(tmp_path):
    s = updater.tausch_skript_schreiben(tmp_path / "app", tmp_path / "app.new", 4242, tmp_path / "app" / "start")
    t = s.read_text()
    assert "4242" in t and "app.new" in t and "app.alt" in t


def test_standort_speichern_laden_und_pruefen(tmp_path, monkeypatch):
    monkeypatch.setattr(standort, "KONFIG", tmp_path / "konfig")
    monkeypatch.setattr(standort, "STANDORT_DATEI", tmp_path / "konfig" / "standort.json")
    assert standort.lade_standort() is None
    ok, meldung = standort.pruefe_ordner(str(tmp_path / "daten"))
    assert ok and (tmp_path / "daten" / "Ausgabe").is_dir() and (tmp_path / "daten" / "Updates").is_dir()
    standort.speichere_standort(meldung)
    assert standort.lade_standort() == tmp_path / "daten"
    assert standort.pruefe_ordner("")[0] is False and standort.pruefe_ordner("relativ/pfad")[0] is False


def test_alte_dateien_werden_einmalig_uebernommen(tmp_path):
    alt = tmp_path / "alt"; alt.mkdir(); (alt / "regeln.json").write_text("{}")
    ausgabe = tmp_path / "Ausgabe"; ausgabe.mkdir(); (ausgabe / "import-2026.xlsx").write_bytes(b"x")
    neu = tmp_path / "neu"; standort.pruefe_ordner(str(neu))
    u = standort.uebernehme_alte_dateien(neu, alt_konfig=alt, alt_ausgabe=ausgabe)
    assert set(u) == {"regeln.json", "Ausgabe/import-2026.xlsx"}
    (neu / "regeln.json").write_text('{"x":1}')
    assert standort.uebernehme_alte_dateien(neu, alt_konfig=alt, alt_ausgabe=ausgabe) == []    # nichts überschreiben
    assert (neu / "regeln.json").read_text() == '{"x":1}'
