"""Datenqualitäts-Checks D1–D10 gemäss Spezifikation Kap. 6.4 (D10: Ergänzung 09.09.2026)."""
from dataclasses import dataclass
from .model import Typ, GRUPPE_UNBEKANNTE


@dataclass
class Hinweis:
    code: str
    schweregrad: str
    text: str
    betroffene: list


def run_checks(accounts, mitglieder, assignments=None):
    hinweise = []
    fg_mit_mitglied = {m.fg for m in mitglieder}
    zweitaccount_ids = {a.id for a in accounts if a.typ == Typ.ZWEITACCOUNT}

    # D1: FG ohne passendes Mitglied
    d1 = [a for a in accounts if a.fg and any(
        f not in fg_mit_mitglied for f in (a.fgs or [a.fg]) if not (a.typ == Typ.MITGLIED and f == a.fg))]
    if d1:
        hinweise.append(Hinweis("D1", "kritisch",
            "FG-Nummer ohne passendes Mitglied — Tippfehler oder Austritt? Im Portal prüfen.",
            [a.anzeigename for a in d1]))

    # D2: Zweitaccount mit Zielwert ≠ 0
    d2 = [a for a in accounts if a.typ == Typ.ZWEITACCOUNT and a.zielwert != 0]
    if d2:
        hinweise.append(Hinweis("D2", "warnung",
            "Zweitaccount mit Zielwert ≠ 0 — Soll würde doppelt zählen. "
            "Korrektur liegt in der Import-Datei des nächsten Abgleichs bereit.",
            [a.anzeigename for a in d2]))

    # D3: mehrere Mitglieds-Accounts pro FG
    d3 = [m for m in mitglieder if m.soll_konflikt]
    if d3:
        hinweise.append(Hinweis("D3", "kritisch",
            "Mehrere Mitglieds-Accounts mit derselben FG-Nummer — im Portal bereinigen. "
            "Das Dashboard rechnet konservativ mit dem höchsten Zielwert.",
            [m.fg for m in d3]))

    # D4: Mitglieds-Gruppe ohne FG
    d4 = [a for a in accounts if a.typ == Typ.MITGLIED and not a.fg]
    if d4:
        hinweise.append(Hinweis("D4", "kritisch",
            "Account in Gruppe «Mitglied» ohne FG-Nummer — wird nicht abgeglichen und "
            "erscheint nicht im Dashboard. FG nachtragen (Autokorrektur via Abgleich möglich).",
            [a.anzeigename for a in d4]))

    # D5: Unbekannte mit Einsätzen oder Anmeldungen
    d5 = [a for a in accounts if a.typ == Typ.UNBEKANNT and (
        a.ist_wert > 0 or a.num_ok or a.num_nok or a.num_confirmed or a.num_reserved or a.num_unconfirmed)]
    if d5:
        hinweise.append(Hinweis("D5", "warnung",
            "Unbekannte mit Einsätzen oder Anmeldungen — Vereinsregel: im Portal zur Gruppe "
            "«Freiwillige» umteilen (von Hand; der Import würde die Gruppenliste ersetzen).",
            [a.anzeigename for a in d5]))

    # D6: vergessene Gutschriften (nur wenn Einsätze verfügbar)
    if assignments is not None:
        d6 = [asg for asg in assignments
              if asg.get("helper") and asg["helper"].get("id") in zweitaccount_ids
              and not asg.get("helpAsHelper")
              and asg.get("status") in ("confirmed", "reserved", "ok")]
        if d6:
            namen = sorted({f"{a['helper'].get('firstName','')} {a['helper'].get('lastName','')}".strip()
                            for a in d6})
            hinweise.append(Hinweis("D6", "hinweis",
                "Einsatz eines Zweitaccounts ohne Gutschrift — zählt im Portal beim Elternteil "
                "(im Cockpit über die FG-Summe trotzdem korrekt).",
                namen))

    # D7: Freiwillige mit Zielwert ≠ 0
    d7 = [a for a in accounts if a.typ == Typ.FREIWILLIG and a.zielwert != 0]
    if d7:
        hinweise.append(Hinweis("D7", "warnung",
            "Freiwillige(r) mit Zielwert ≠ 0 — Autokorrektur via Import-Datei.",
            [a.anzeigename for a in d7]))

    # D8: FG-Schreibweise abweichend
    d8 = [a for a in accounts if a.fg and a.fg_nonstandard]
    if d8:
        hinweise.append(Hinweis("D8", "hinweis",
            "FG-Schreibweise abweichend von «FG-<Zahl>» am Bemerkungsanfang — wird toleriert "
            "gelesen; im Portal vereinheitlichen.",
            [f"{a.anzeigename}: «{a.bemerkung}»" for a in d8]))

    # D9: unklassifiziert oder FG in Gruppe «Unbekannte»
    d9 = [a for a in accounts if a.typ == Typ.UNKLASSIFIZIERT
          or (a.fg and GRUPPE_UNBEKANNTE in a.gruppen)]
    if d9:
        hinweise.append(Hinweis("D9", "warnung",
            "Account entspricht keinem gültigen Muster — klären und umteilen.",
            [a.anzeigename for a in d9]))

    # D10: namensgleiche Accounts, einer mit FG-Nummer, einer ohne → vermutlich hat sich die
    # Person mit neuer E-Mail NEU registriert statt die Adresse zu ändern. Der neue Account
    # sammelt Einsätze, die dem Mitglied nicht zugerechnet werden.
    nach_name = {}
    for a in accounts:
        nach_name.setdefault((a.vorname.strip().lower(), a.nachname.strip().lower()), []).append(a)
    d10 = []
    for gruppe in nach_name.values():
        mit = [a for a in gruppe if a.fg]
        ohne = [a for a in gruppe if not a.fg]
        if mit and ohne:
            for a in ohne:
                einsaetze = a.num_ok + a.num_confirmed
                d10.append(f"{a.anzeigename} (ohne FG, {einsaetze} Einsätze) — daneben "
                           f"{', '.join(m.fg for m in mit)}")
    if d10:
        hinweise.append(Hinweis("D10", "warnung",
            "Namensgleiche Accounts mit und ohne FG-Nummer — vermutlich Neuregistrierung mit "
            "neuer E-Mail. Im Portal zusammenführen (Einsätze des neuen Accounts gehen dem "
            "Mitglied sonst verloren).",
            sorted(d10)))

    return hinweise
