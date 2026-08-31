"""Ausgabedateien: Import-Excel (Portal-Format), Säumigen-CSV, Handarbeitsliste."""
import csv
import html as html_mod
from pathlib import Path
import openpyxl
from .model import status

IMPORT_SPALTEN = ["Vorname", "Nachname", "E-Mail", "Telefon", "Gruppe",
                  "zusätzliche E-Mail (1)", "zusätzliche E-Mail (2)", "Geburtsdatum",
                  "Geschlecht", "Individueller Zielwert", "Bemerkungen"]

_SICHT_NAME = {"saison": "Saison-Soll", "halbjahr": "Halbjahresziel"}


def schreibe_import_xlsx(zeilen, pfad):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Import"
    ws.append(IMPORT_SPALTEN)
    for z in zeilen:
        ws.append([z.vorname or None, z.nachname or None, z.email or None, z.telefon or None,
                   z.gruppe or None, z.zusatz_email1 or None, z.zusatz_email2 or None,
                   z.geburtsdatum or None, z.geschlecht or None, z.zielwert or None,
                   z.bemerkungen or None])
    wb.save(pfad)


MITGLIEDER_SPALTEN = ["FG-Nummer", "Name", "Gruppen", "Soll", "Ist",
                      "Status Saison", "Status Halbjahr", "Anzahl Accounts"]
ACCOUNTS_SPALTEN = ["FG-Nummer", "Name", "Typ", "Zielwert", "Ist-Wert", "Bemerkung"]


def schreibe_gesamtexport_xlsx(mitglieder, halbjahresziel, pfad):
    """Excel-Gesamtexport (Spez. 6.1): ein Blatt pro Mitglied, ein Blatt pro Account."""
    wb = openpyxl.Workbook()
    ws_m = wb.active
    ws_m.title = "Mitglieder"
    ws_m.append(MITGLIEDER_SPALTEN)
    ws_a = wb.create_sheet("Accounts")
    ws_a.append(ACCOUNTS_SPALTEN)
    for m in mitglieder:
        a0 = m.mitglieds_account
        ws_m.append([m.fg, a0.anzeigename, ", ".join(a0.gruppen), m.soll, m.ist,
                    status(m, "saison", halbjahresziel), status(m, "halbjahr", halbjahresziel),
                    len(m.accounts)])
        for a in m.accounts:
            ws_a.append([m.fg, a.anzeigename, a.typ.value, a.zielwert, a.ist_wert, a.bemerkung])
    wb.save(pfad)
    return len(mitglieder)


def schreibe_saeumigen_csv(mitglieder, sicht, halbjahresziel, pfad):
    saeumige = []
    for m in mitglieder:
        s = status(m, sicht, halbjahresziel)
        ziel = m.soll if sicht == "saison" else halbjahresziel
        if s != "erfuellt" and m.ist < ziel:
            saeumige.append(m)
    with Path(pfad).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([f"Säumigen-Liste — Sicht: {_SICHT_NAME[sicht]}"])
        w.writerow(["Vorname", "Nachname", "E-Mail", "FG-Nummer", "Soll", "Ist"])
        for m in saeumige:
            a = m.mitglieds_account
            w.writerow([a.vorname, a.nachname, a.email, m.fg, f"{m.soll:g}", f"{m.ist:g}"])
    return len(saeumige)


def handarbeitsliste_html(e):
    def punkt(text):
        return ('<li><label><input type="checkbox"> ' + html_mod.escape(text) + "</label></li>")
    schluessel = [h for h in e.handarbeit if h.art == "schluessel"]
    austritte = [h for h in e.handarbeit if h.art == "austritt"]
    leerungen = [h for h in e.handarbeit if h.art == "leerung"]
    teile = ["<meta charset='utf-8'><title>Handarbeits-Liste</title>",
             "<style>body{font:15px/1.6 sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem}"
             "li{margin:.4rem 0}@media print{input{-webkit-print-color-adjust:exact}}</style>",
             f"<h1>Handarbeits-Liste</h1><p><b>{html_mod.escape(e.zusammenfassung)}</b></p>",
             "<p><b>Reihenfolge:</b> zuerst diese Liste im Portal abarbeiten "
             "(Schlüssel-Änderungen vor allem!), erst danach die Import-Datei hochladen — "
             "sonst entstehen Duplikate.</p>"]
    if schluessel:
        teile.append("<h2>1 · Schlüssel-Änderungen (zuerst!)</h2><ul>")
        teile += [punkt(f"{h.name} ({h.fg}): {h.detail}") for h in schluessel]
        teile.append("</ul>")
    if austritte:
        teile.append("<h2>2 · Austritte deaktivieren</h2><ul>")
        teile += [punkt(f"{h.name} ({h.fg}): {h.detail}") for h in austritte]
        teile.append("</ul>")
    if leerungen:
        teile.append("<h2>3 · Felder leeren</h2><ul>")
        teile += [punkt(f"{h.name} ({h.fg}): {h.detail}") for h in leerungen]
        teile.append("</ul>")
    if e.duplikat_warnungen:
        teile.append("<h2>Duplikat-Warnungen (nicht importiert)</h2><ul>")
        teile += [punkt(t) for t in e.duplikat_warnungen]
        teile.append("</ul>")
    if e.klaerliste:
        teile.append("<h2>Klärliste (in Fairgate nachtragen)</h2><ul>")
        teile += [punkt(t) for t in e.klaerliste]
        teile.append("</ul>")
    if e.unbekannte_kategorien:
        teile.append("<h2>Unbekannte Fairgate-Kategorien (Regeln prüfen)</h2><ul>")
        teile += [punkt(t) for t in e.unbekannte_kategorien]
        teile.append("</ul>")
    if not (schluessel or austritte or leerungen or e.duplikat_warnungen or e.klaerliste
            or e.unbekannte_kategorien):
        teile.append("<p>Nichts zu tun — alles synchron. 🎉</p>")
    return "\n".join(teile)
