import csv
import openpyxl
from cockpit.abgleich import ImportZeile, AbgleichErgebnis, HandarbeitsFall
from cockpit.exports import (IMPORT_SPALTEN, schreibe_import_xlsx,
                             schreibe_saeumigen_csv, handarbeitsliste_html)
from cockpit.model import Mitglied, Account, Typ


def _acc(vn, nn, mail):
    return Account(id=1, vorname=vn, nachname=nn, email=mail, telefon="", geburtsdatum="",
                   bemerkung="", gruppen=["Mitglied"], fg="FG-1", fg_nonstandard=False,
                   typ=Typ.MITGLIED, zielwert=2, ist_wert=0, num_ok=0, num_nok=0,
                   num_confirmed=0, num_reserved=0, num_unconfirmed=0)


def test_import_xlsx_golden(tmp_path):
    pfad = tmp_path / "import.xlsx"
    schreibe_import_xlsx([ImportZeile(vorname="Neu", nachname="Kind",
                                      email="eltern@example.ch", gruppe="Mitglied",
                                      zielwert="2", bemerkungen="FG-9")], pfad)
    ws = openpyxl.load_workbook(pfad).active
    assert [c.value for c in ws[1]] == IMPORT_SPALTEN
    zeile = [c.value for c in ws[2]]
    assert zeile[0] == "Neu" and zeile[9] == "2" and zeile[10] == "FG-9"
    assert zeile[4] == "Mitglied" and zeile[3] is None  # leere Zellen bleiben leer


def test_saeumigen_csv_folgt_der_sicht(tmp_path):
    m_halb = Mitglied(fg="FG-1", accounts=[_acc("Lina", "Brunner", "l@example.ch")], soll=2, ist=1)
    m_ok = Mitglied(fg="FG-2", accounts=[_acc("Noah", "Keller", "n@example.ch")], soll=2, ist=2)
    pfad = tmp_path / "saeumige.csv"
    n = schreibe_saeumigen_csv([m_halb, m_ok], "saison", 1, pfad)
    assert n == 1
    zeilen = list(csv.reader(pfad.open(encoding="utf-8-sig"), delimiter=";"))
    assert "Saison-Soll" in zeilen[0][0]          # Sicht in der Kopfzeile
    assert zeilen[2][0] == "Lina"                  # Kopfzeile Sicht + Spaltenkopf + Daten
    assert schreibe_saeumigen_csv([m_halb, m_ok], "halbjahr", 1, tmp_path / "h.csv") == 0


def test_handarbeitsliste_html():
    e = AbgleichErgebnis(handarbeit=[HandarbeitsFall("austritt", "Weg Gezogen", "FG-1", "deaktivieren")],
                         klaerliste=["Fall X"], zusammenfassung="1 Austritt bei 3 geprüften Mitgliedern.")
    html = handarbeitsliste_html(e)
    assert "Weg Gezogen" in html and "checkbox" in html
    assert "zuerst" in html.lower()               # Reihenfolge-Hinweis
    assert "Fall X" in html
