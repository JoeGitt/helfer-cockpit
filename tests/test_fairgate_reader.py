import pytest
import openpyxl
from cockpit.fairgate_reader import lies_fairgate, FalscheDatei

KOPF = ["Kontakte", "Kontakt-ID Verein", "Primäre E-Mail", "Vorname", "Nachname",
        "Handy", "Mitgliedschaft", "E-Mail Eltern 1", "E-Mail Eltern 2", "Geburtsdatum"]

def _schreibe(tmp_path, kopf, zeilen):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(kopf)
    for z in zeilen:
        ws.append(z)
    pfad = tmp_path / "export.xlsx"
    wb.save(pfad)
    return pfad

def test_liest_kontakte(tmp_path):
    pfad = _schreibe(tmp_path, KOPF, [
        ["x", 2417, "lina@example.ch", "Lina", "Brunner", "0791112233",
         "Aktivmitglied", "eltern@example.ch", None, "2012-04-01"],
        ["x", 9999, None, "Ohne", "Mail", None, "Aktivmitglied", None, None, None],
    ])
    kontakte = lies_fairgate(pfad)
    assert len(kontakte) == 2
    k = kontakte[0]
    assert k.fg == "FG-2417" and k.vorname == "Lina" and k.kategorie == "Aktivmitglied"
    assert k.eltern_email == "eltern@example.ch"
    assert kontakte[1].email == "" and kontakte[1].eltern_email == ""

def test_weist_falsche_datei_ab(tmp_path):
    pfad = _schreibe(tmp_path, ["Vorname Helfer/in", "Nachname Helfer/in"], [["A", "B"]])
    with pytest.raises(FalscheDatei) as e:
        lies_fairgate(pfad)
    assert "Aktualisierungsimport" in str(e.value)

def test_leere_zeilen_werden_uebersprungen(tmp_path):
    pfad = _schreibe(tmp_path, KOPF, [[None] * 10])
    assert lies_fairgate(pfad) == []


def test_garbage_datei_wird_als_falsche_datei_abgewiesen(tmp_path):
    pfad = tmp_path / "kaputt.xlsx"
    pfad.write_bytes(b"das ist keine Excel-Datei, nur Muell-Bytes \x00\x01\x02")
    with pytest.raises(FalscheDatei) as e:
        lies_fairgate(pfad)
    assert "Aktualisierungsimport" in str(e.value)


def test_liest_kontakte_aus_bytesio(tmp_path):
    import io
    pfad = _schreibe(tmp_path, KOPF, [
        ["x", 2417, "lina@example.ch", "Lina", "Brunner", "0791112233",
         "Aktivmitglied", "eltern@example.ch", None, "2012-04-01"],
    ])
    with io.BytesIO(pfad.read_bytes()) as puffer:
        kontakte = lies_fairgate(puffer)
    assert len(kontakte) == 1 and kontakte[0].fg == "FG-2417"
