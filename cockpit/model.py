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
    """Erste FG-Nummer der Bemerkung (= eigene Nummer) und ob sie nicht im Standardformat steht."""
    if not text:
        return (None, False)
    m = _FG_MUSTER.search(text)
    if not m:
        return (None, False)
    fg = f"FG-{m.group(1)}"
    standard = m.start() == 0 and text[m.start():m.end()] == fg
    return (fg, not standard)


def normalize_fgs(text: str | None) -> list:
    """Alle FG-Nummern der Bemerkung in Reihenfolge, ohne Doppelte. Konvention (Spez 6.11):
    die erste ist die eigene Nummer, weitere verbinden den Account mit einer Familie."""
    if not text:
        return []
    gesehen, fgs = set(), []
    for m in _FG_MUSTER.finditer(text):
        fg = f"FG-{m.group(1)}"
        if fg not in gesehen:
            gesehen.add(fg); fgs.append(fg)
    return fgs


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
    fgs: list = None            # alle FG-Nummern der Bemerkung (erste = fg)
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
        fgs=normalize_fgs(helper.get("adminRemarks")),
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
class Familie:
    """Mehrere Mitglieder, deren Accounts über gemeinsame FG-Nummern verbunden sind (Spez 6.11).
    Topf-Regel: Soll = Summe der Solls, Ist = Einsätze aller Accounts der Familie, egal auf welchem."""
    name: str
    fgs: list           # FG-Nummern der Mitglieder (sortiert)
    accounts: list      # alle Accounts der Familie, jeder genau einmal
    soll: float
    ist: float

    @property
    def schluessel(self):
        return self.fgs[0]


@dataclass
class Mitglied:
    """Ein Mitglied mit aggregierten Daten über FG-Nummer."""
    fg: str
    accounts: list
    soll: float
    ist: float
    soll_konflikt: bool = False
    familie: Familie | None = None

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
        # Zweitaccounts mit mehreren Nummern gehören der Familie, nicht einem einzelnen Mitglied
        if a.fg and (a.typ == Typ.MITGLIED or len(a.fgs or []) <= 1):
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
    _familien_bilden(accounts, mitglieder)
    return mitglieder


def _familien_bilden(accounts, mitglieder):
    """Accounts mit mehreren FG-Nummern verbinden Mitglieder zu einer Familie (Union-Find über
    die Nummern). Eine Familie braucht mindestens zwei Mitglieder mit Mitglieds-Account."""
    eltern = {}
    def wurzel(x):
        while eltern.get(x, x) != x:
            x = eltern[x]
        return x
    def verbinde(x, y):
        rx, ry = wurzel(x), wurzel(y)
        if rx != ry:
            eltern[max(rx, ry)] = min(rx, ry)
    for a in accounts:
        for fg in (a.fgs or [])[1:]:
            verbinde(a.fgs[0], fg)
    nach_fg = {m.fg: m for m in mitglieder}
    gruppen = {}
    for m in mitglieder:
        gruppen.setdefault(wurzel(m.fg), []).append(m)
    for ms in gruppen.values():
        if len(ms) < 2:
            continue
        fgs = sorted(m.fg for m in ms)
        beteiligt, gesehen = [], set()
        for a in accounts:
            if a.id not in gesehen and any(wurzel(fg) == wurzel(fgs[0]) for fg in (a.fgs or [])):
                gesehen.add(a.id); beteiligt.append(a)
        nachnamen = []
        for m in ms:
            nn = m.mitglieds_account.nachname.strip()
            if nn and nn not in nachnamen:
                nachnamen.append(nn)
        fam = Familie(name="Familie " + " / ".join(nachnamen), fgs=fgs, accounts=beteiligt,
                      soll=sum(m.soll for m in ms), ist=sum(a.ist_wert for a in beteiligt))
        for m in ms:
            m.familie = fam
    # Zweitaccount mit mehreren Nummern, aber ohne Familie (nur ein Mitglied vorhanden):
    # zählt wie bisher beim ersten Mitglied
    for a in accounts:
        if a.fg and a.typ != Typ.MITGLIED and len(a.fgs or []) > 1 and a.fg in nach_fg and not nach_fg[a.fg].familie:
            nach_fg[a.fg].accounts.append(a)
            nach_fg[a.fg].ist += a.ist_wert


def status(m, sicht, halbjahresziel):
    """Bestimmt den Status eines Mitglieds.

    sicht: "saison" oder "halbjahr"
    Rückgabe: "erfuellt" | "auf_kurs" | "saeumig"
    (Halbjahr-Sicht kennt kein "auf_kurs")
    """
    if m.familie:                # Topf-Regel: die Familie ist gemeinsam erfüllt oder säumig
        n = len(m.familie.fgs)
        ziel = m.familie.soll if sicht == "saison" else float(halbjahresziel) * n
        ist = m.familie.ist
    else:
        ziel = m.soll if sicht == "saison" else float(halbjahresziel)
        ist = m.ist
    if ist >= ziel and ziel > 0:
        return "erfuellt"
    if sicht == "saison" and 0 < ist < ziel:
        return "auf_kurs"
    if ist >= ziel:              # ziel 0 (z.B. Soll 0) gilt als erfüllt
        return "erfuellt"
    return "saeumig"
