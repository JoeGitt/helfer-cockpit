"""Liest den Fairgate-Export «Aktive Kontakte» (für Aktualisierungsimport optimiert)."""
import zipfile
from dataclasses import dataclass, field
import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

PFLICHT = ["Kontakt-ID Verein", "Vorname", "Nachname", "Mitgliedschaft"]
EXPORTWEG = ("Fairgate: Kontaktverwaltung → Aktive Kontakte → Exportieren, Haken bei "
             "«für Aktualisierungsimport optimieren» (bringt die Kontakt-ID mit).")


class FalscheDatei(Exception):
    pass


@dataclass
class FgKontakt:
    fg: str
    vorname: str
    nachname: str
    email: str
    telefon: str
    geburtsdatum: str
    kategorie: str
    eltern_email: str
    alle_emails: list = field(default_factory=list)   # jede Adresse des Kontakts (eigene, Eltern, weitere)


def _zelle(zeile, idx):
    if idx is None or idx >= len(zeile) or zeile[idx] is None:
        return ""
    return str(zeile[idx]).strip()


def lies_fairgate(pfad):
    try:
        wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException) as exc:
        raise FalscheDatei(
            "Das ist keine gültige Excel-Datei (.xlsx). Richtiger Weg: %s" % EXPORTWEG) from exc
    except Exception as exc:
        raise FalscheDatei(
            "Die Datei konnte nicht gelesen werden (%s). Richtiger Weg: %s"
            % (exc, EXPORTWEG)) from exc
    try:
        ws = wb.active
        zeilen = ws.iter_rows(values_only=True)
        kopf = [str(c).strip() if c is not None else "" for c in next(zeilen, [])]
        fehlend = [s for s in PFLICHT if s not in kopf]
        if fehlend:
            raise FalscheDatei(
                "Das ist kein Fairgate-Kontakt-Export (fehlende Spalten: %s). Richtiger Weg: %s"
                % (", ".join(fehlend), EXPORTWEG))
        def spalte(name):
            return kopf.index(name) if name in kopf else None
        i_id, i_vn, i_nn = spalte("Kontakt-ID Verein"), spalte("Vorname"), spalte("Nachname")
        i_mail, i_tel, i_geb = spalte("Primäre E-Mail"), spalte("Handy"), spalte("Geburtsdatum")
        i_kat, i_e1, i_e2 = spalte("Mitgliedschaft"), spalte("E-Mail Eltern 1"), spalte("E-Mail Eltern 2")
        i_weitere = [spalte(n) for n in ("E-Mail 2", "Mail 2") if spalte(n) is not None]
        kontakte = []
        for zeile in zeilen:
            nummer = _zelle(zeile, i_id)
            if not nummer:
                continue
            nummer = nummer.split(".")[0]  # openpyxl liefert Zahlen ggf. als float
            kontakte.append(FgKontakt(
                fg=f"FG-{nummer}",
                vorname=_zelle(zeile, i_vn),
                nachname=_zelle(zeile, i_nn),
                email=_zelle(zeile, i_mail),
                telefon=_zelle(zeile, i_tel),
                geburtsdatum=_zelle(zeile, i_geb)[:10],
                kategorie=_zelle(zeile, i_kat),
                eltern_email=_zelle(zeile, i_e1) or _zelle(zeile, i_e2),
                alle_emails=[m for m in dict.fromkeys(
                    [_zelle(zeile, i_mail), _zelle(zeile, i_e1), _zelle(zeile, i_e2)]
                    + [_zelle(zeile, i) for i in i_weitere]) if m],
            ))
        return kontakte
    finally:
        wb.close()
