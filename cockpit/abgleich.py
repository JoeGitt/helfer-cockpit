"""Quartals-Abgleich Fairgate → Portal (Spez. Kap. 6.3). Liest nur, schreibt nie."""
import datetime
from dataclasses import dataclass, field
from .model import Typ


@dataclass
class ImportZeile:
    vorname: str = ""
    nachname: str = ""
    email: str = ""
    telefon: str = ""
    gruppe: str = ""
    zusatz_email1: str = ""
    zusatz_email2: str = ""
    geburtsdatum: str = ""
    geschlecht: str = ""
    zielwert: str = ""
    bemerkungen: str = ""


@dataclass
class HandarbeitsFall:
    art: str      # "austritt" | "schluessel"
    name: str
    fg: str
    detail: str


@dataclass
class AbgleichErgebnis:
    neueintritte: list = field(default_factory=list)
    korrekturen: list = field(default_factory=list)
    handarbeit: list = field(default_factory=list)
    klaerliste: list = field(default_factory=list)
    duplikat_warnungen: list = field(default_factory=list)
    zusammenfassung: str = ""
    geprueft: int = 0


def _alter(geburtsdatum, heute):
    try:
        geb = datetime.date.fromisoformat(geburtsdatum[:10])
    except (ValueError, TypeError):
        return None
    return heute.year - geb.year - ((heute.month, heute.day) < (geb.month, geb.day))


def _ziel_email(kontakt, regeln, heute):
    alter = _alter(kontakt.geburtsdatum, heute)
    if alter is not None and alter < regeln.altersgrenze:
        return kontakt.eltern_email or kontakt.email
    return kontakt.email or kontakt.eltern_email


def _schluessel(vn, nn, mail):
    return (vn, nn, mail)                       # case-SENSITIV (Portal-Match)


def _lax(vn, nn, mail):
    return (vn.strip().lower(), nn.strip().lower(), mail.strip().lower())


def gleiche_ab(kontakte, accounts, regeln, heute=None):
    heute = heute or datetime.date.today()
    e = AbgleichErgebnis(geprueft=len(kontakte))
    portal_mitglieder = [a for a in accounts if a.typ == Typ.MITGLIED]

    # Sicherheitsstopp (Spez. 6.3): Grossteil ohne FG → irreführende Ergebnisse vermeiden
    if portal_mitglieder:
        ohne_fg = sum(1 for a in portal_mitglieder if not a.fg)
        if ohne_fg >= 2 and ohne_fg / len(portal_mitglieder) > 0.5:
            raise ValueError(
                "Bei %d von %d Portal-Mitgliedern fehlt die FG-Nummer — Abgleich gestoppt, "
                "sonst wären die Ergebnisse irreführend. Zuerst FG-Nummern nachrüsten."
                % (ohne_fg, len(portal_mitglieder)))

    portal_nach_fg = {a.fg: a for a in portal_mitglieder if a.fg}
    portal_lax = {_lax(a.vorname, a.nachname, a.email) for a in accounts}
    fairgate_fgs = set()

    for k in kontakte:
        regel = regeln.fuer_kategorie(k.kategorie)
        if regel is None:
            continue                             # nicht helferpflichtig
        fairgate_fgs.add(k.fg)
        konto = portal_nach_fg.get(k.fg)
        if konto is None:
            mail = _ziel_email(k, regeln, heute)
            if not mail:
                e.klaerliste.append(f"{k.vorname} {k.nachname} ({k.fg}): keine erreichbare "
                                    "E-Mail (weder eigene noch Haushalt) — in Fairgate nachtragen.")
                continue
            if _lax(k.vorname, k.nachname, mail) in portal_lax:
                e.duplikat_warnungen.append(
                    f"{k.vorname} {k.nachname} ({k.fg}): existiert im Portal in abweichender "
                    "Schreibweise — nicht importiert (Duplikat-Gefahr), von Hand klären.")
                continue
            e.neueintritte.append(ImportZeile(
                vorname=k.vorname, nachname=k.nachname, email=mail, telefon=k.telefon,
                gruppe=regel.portal_gruppe, geburtsdatum=k.geburtsdatum,
                zielwert=str(regel.zielwert), bemerkungen=k.fg))
        else:
            # Schlüssel-Änderung? Referenz-Schreibweise ist das PORTAL (case-sensitiv).
            mail = _ziel_email(k, regeln, heute)
            portal_mails = {konto.email, konto.zusatz_email1, konto.zusatz_email2} - {""}
            if mail and mail not in portal_mails:
                e.handarbeit.append(HandarbeitsFall(
                    "schluessel", konto.anzeigename, k.fg,
                    f"E-Mail in Fairgate neu: {mail} (Portal: {konto.email}) — zuerst im "
                    "Portal nachführen, sonst legt der Import ein Duplikat an."))
            # Wert-Korrekturen (Update-Import, Tripel aus dem Portal, Gruppen-Spalte leer!)
            aenderungen = {}
            if konto.zielwert != regel.zielwert:
                aenderungen["zielwert"] = str(regel.zielwert)
            if k.telefon and k.telefon != konto.telefon:
                aenderungen["telefon"] = k.telefon
            if aenderungen:
                e.korrekturen.append(ImportZeile(
                    vorname=konto.vorname, nachname=konto.nachname, email=konto.email,
                    bemerkungen=konto.fg or k.fg, **aenderungen))

    # Austritte: Portal-Mitglied, dessen FG in Fairgate (pflichtige Kategorien) fehlt
    for fg, konto in sorted(portal_nach_fg.items()):
        if fg not in fairgate_fgs:
            e.handarbeit.append(HandarbeitsFall(
                "austritt", konto.anzeigename, fg,
                "In Fairgate nicht mehr als pflichtiges Mitglied geführt — im Portal "
                "deaktivieren (der Import löscht nichts)."))

    # Zweitaccounts/Freiwillige mit Zielwert ≠ 0 → Korrektur auf 0 (Spez. D2/D7)
    for a in accounts:
        if a.typ in (Typ.ZWEITACCOUNT, Typ.FREIWILLIG) and a.zielwert != 0:
            e.korrekturen.append(ImportZeile(
                vorname=a.vorname, nachname=a.nachname, email=a.email,
                zielwert="0", bemerkungen=a.bemerkung))

    teile = []
    if e.neueintritte: teile.append(f"{len(e.neueintritte)} Neueintritte")
    austritte = [h for h in e.handarbeit if h.art == "austritt"]
    if austritte: teile.append(f"{len(austritte)} Austritte")
    if e.korrekturen: teile.append(f"{len(e.korrekturen)} Korrektionen")
    e.zusammenfassung = ((", ".join(teile) if teile else "Alles synchron")
                         + f" bei {e.geprueft} geprüften Mitgliedern.")
    return e
