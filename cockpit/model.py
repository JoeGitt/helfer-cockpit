"""Datenmodell: FG-Normalisierung, Typ-Erkennung, Aggregation, Status.

Regeln gemäss SPEZIFIKATION-helfer-cockpit-2.md Kap. 4+5. Die Erkennung
liegt bewusst komplett in diesem Modul (eine Stelle für spätere Regel-Wechsel).
"""
import re
from dataclasses import dataclass
from enum import Enum

# FG irgendwo in der Bemerkung erkennen (Spez. Kap. 4): case-insensitiv,
# Trennzeichen-tolerant. Eine nicht erkannte Nummer wäre ein stiller Fehler.
_FG_MUSTER = re.compile(r"fg[\s\-–—_]*([0-9]{1,8})", re.IGNORECASE)


def normalize_fg(text: str | None) -> tuple[str | None, bool]:
    if not text:
        return (None, False)
    m = _FG_MUSTER.search(text)
    if not m:
        return (None, False)
    fg = f"FG-{m.group(1)}"
    standard = m.start() == 0 and text[m.start():m.end()] == fg
    return (fg, not standard)


GRUPPE_MITGLIED = "Mitglied"
GRUPPE_FREIWILLIGE = "Freiwillige"
GRUPPE_UNBEKANNTE = "Unbekannte"


class Typ(str, Enum):
    """Klassifizierung eines Helpers in die fünf Typen."""
    MITGLIED = "mitglied"
    ZWEITACCOUNT = "zweitaccount"
    FREIWILLIG = "freiwillig"
    UNBEKANNT = "unbekannt"
    UNKLASSIFIZIERT = "unklassifiziert"


@dataclass
class Account:
    """Ein Helper-Account mit allen Metadaten und berechneten Werten."""
    id: int
    vorname: str
    nachname: str
    email: str
    telefon: str
    geburtsdatum: str
    bemerkung: str
    gruppen: list
    fg: str | None
    fg_nonstandard: bool
    typ: Typ
    zielwert: float
    ist_wert: float
    num_ok: int
    num_nok: int
    num_confirmed: int
    num_reserved: int
    num_unconfirmed: int
    zusatz_email1: str = ""
    zusatz_email2: str = ""

    @property
    def anzeigename(self):
        """Formatierter Name: 'Vorname Nachname', ohne Leerzeichen wenn eines fehlt."""
        return f"{self.vorname} {self.nachname}".strip()


def _gruppennamen(groups):
    """Extrahiert Namen aus der Groups-Struktur."""
    if not groups:
        return []
    items = groups.values() if isinstance(groups, dict) else groups
    namen = []
    for it in items:
        namen.append(str(it.get("name", "")).strip() if isinstance(it, dict) else str(it).strip())
    return [n for n in namen if n]


def classify(helper):
    """Klassifiziert einen Raw-Helper-Dict zu einem Account mit Typ."""
    sc = helper.get("stateCache") or {}
    gruppen = _gruppennamen(helper.get("groups"))
    fg, nonstandard = normalize_fg(helper.get("adminRemarks"))
    if fg and GRUPPE_MITGLIED in gruppen:
        typ = Typ.MITGLIED
    elif fg:
        typ = Typ.ZWEITACCOUNT
    elif GRUPPE_MITGLIED in gruppen:
        typ = Typ.MITGLIED       # Regelverstoss ohne FG → Check D4 meldet
    elif GRUPPE_FREIWILLIGE in gruppen:
        typ = Typ.FREIWILLIG
    elif GRUPPE_UNBEKANNTE in gruppen:
        typ = Typ.UNBEKANNT
    else:
        typ = Typ.UNKLASSIFIZIERT
    return Account(
        id=helper.get("id"),
        vorname=helper.get("firstName") or "",
        nachname=helper.get("lastName") or "",
        email=helper.get("email") or "",
        telefon=helper.get("phone") or "",
        geburtsdatum=helper.get("birthDate") or "",
        bemerkung=helper.get("adminRemarks") or "",
        gruppen=gruppen,
        fg=fg,
        fg_nonstandard=nonstandard,
        typ=typ,
        zielwert=float(sc.get("requestedValue") or 0),
        ist_wert=float(sc.get("plannedValue") or 0),
        num_ok=int(sc.get("okAssignmentsNum") or 0),
        num_nok=int(sc.get("nokAssignmentsNum") or 0),
        num_confirmed=int(sc.get("confirmedAssignmentsNum") or 0),
        num_reserved=int(sc.get("reservedAssignmentsNum") or 0),
        num_unconfirmed=int(sc.get("unconfirmedAssignmentsNum") or 0),
        zusatz_email1=helper.get("additionalEmail1") or "",
        zusatz_email2=helper.get("additionalEmail2") or "",
    )


@dataclass
class Mitglied:
    """Ein Mitglied mit aggregierten Daten über FG-Nummer."""
    fg: str
    accounts: list
    soll: float
    ist: float
    soll_konflikt: bool = False

    @property
    def mitglieds_account(self):
        """Gibt den ersten Account mit Typ MITGLIED zurück, oder None."""
        for a in self.accounts:
            if a.typ == Typ.MITGLIED:
                return a
        return None


def build_mitglieder(accounts):
    """Aggregiert Accounts nach FG-Nummer zu Mitglieder-Objekten.

    Ist = Summe der ist_wert-Felder aller Accounts derselben FG-Nummer.
    Soll = max(zielwert) der Mitglieds-Accounts der FG.
    Bei mehreren Mitglieds-Accounts soll_konflikt=True setzen.
    """
    nach_fg = {}
    for a in accounts:
        if a.fg:
            nach_fg.setdefault(a.fg, []).append(a)
    mitglieder = []
    for fg, gruppe in sorted(nach_fg.items()):
        haupt = [a for a in gruppe if a.typ == Typ.MITGLIED]
        if not haupt:
            continue  # FG ohne Mitglied → Check D1, kein Dashboard-Eintrag
        soll = max(a.zielwert for a in haupt)
        ist = sum(a.ist_wert for a in gruppe)
        mitglieder.append(Mitglied(fg=fg, accounts=gruppe, soll=soll, ist=ist,
                                   soll_konflikt=len(haupt) > 1))
    return mitglieder


def status(m, sicht, halbjahresziel):
    """Bestimmt den Status eines Mitglieds.

    sicht: "saison" oder "halbjahr"
    Rückgabe: "erfuellt" | "auf_kurs" | "saeumig"
    (Halbjahr-Sicht kennt kein "auf_kurs")
    """
    ziel = m.soll if sicht == "saison" else float(halbjahresziel)
    if m.ist >= ziel and ziel > 0:
        return "erfuellt"
    if sicht == "saison" and 0 < m.ist < ziel:
        return "auf_kurs"
    if m.ist >= ziel:            # ziel 0 (z.B. Soll 0) gilt als erfüllt
        return "erfuellt"
    return "saeumig"
