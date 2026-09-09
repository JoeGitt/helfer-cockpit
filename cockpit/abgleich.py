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
    art: str      # "austritt" | "schluessel" | "leerung"
    name: str
    fg: str
    detail: str
    helper_id: int = None     # Portal-Account, um direkt dorthin zu springen


@dataclass
class AbgleichErgebnis:
    neueintritte: list = field(default_factory=list)
    korrekturen: list = field(default_factory=list)
    handarbeit: list = field(default_factory=list)
    klaerliste: list = field(default_factory=list)
    duplikat_warnungen: list = field(default_factory=list)
    unbekannte_kategorien: list = field(default_factory=list)
    kontakt_abweichungen: list = field(default_factory=list)   # Info-Liste: E-Mail Portal ≠ Fairgate
    kategorien: dict = field(default_factory=dict)             # {"pflichtig": {..}, "nicht_pflichtig": {..}, "unbekannt": {..}}
    zusammenfassung: str = ""
    geprueft: int = 0


def _alter(geburtsdatum, heute):
    if not geburtsdatum:
        return None
    text = geburtsdatum[:10].strip()
    try:
        geb = datetime.date.fromisoformat(text)
    except ValueError:
        try:
            geb = datetime.datetime.strptime(text, "%d.%m.%Y").date()
        except ValueError:
            return None
    return heute.year - geb.year - ((heute.month, heute.day) < (geb.month, geb.day))


def _ziel_email(kontakt, regeln, heute):
    alter = _alter(kontakt.geburtsdatum, heute)
    if alter is not None and alter < regeln.altersgrenze:
        return kontakt.eltern_email or kontakt.email
    return kontakt.email or kontakt.eltern_email


def _lax(vn, nn, mail):
    return (vn.strip().lower(), nn.strip().lower(), mail.strip().lower())


def _fairgate_adressen(k):
    """Alle Adressen des Kontakts, kleingeschrieben — die Person ist über jede davon erreichbar."""
    return {m.strip().lower() for m in (list(k.alle_emails) + [k.email, k.eltern_email]) if m}


def _gruppen_vereinigt(konto, portal_gruppe):
    """Gruppen-Spalte für den Update-Import: bestehende Gruppen + Zielgruppe (die Spalte ERSETZT
    die Gruppenliste, darum immer die Vereinigung schreiben — Spez. 6.3)."""
    gruppen = list(konto.gruppen)
    if portal_gruppe and portal_gruppe not in gruppen:
        gruppen.append(portal_gruppe)
    return ", ".join(gruppen)


def gleiche_ab(kontakte, accounts, regeln, heute=None):
    heute = heute or datetime.date.today()
    e = AbgleichErgebnis(geprueft=len(kontakte))
    portal_mitglieder = [a for a in accounts if a.typ == Typ.MITGLIED]

    # Sicherheitsstopp (Spez. 6.3): Grossteil ohne FG → irreführende Ergebnisse vermeiden
    if portal_mitglieder:
        ohne_fg = sum(1 for a in portal_mitglieder if not a.fg)
        if ohne_fg / len(portal_mitglieder) > 0.5:
            raise ValueError(
                "Bei %d von %d Portal-Mitgliedern fehlt die FG-Nummer — Abgleich gestoppt, "
                "sonst wären die Ergebnisse irreführend. Zuerst FG-Nummern nachrüsten."
                % (ohne_fg, len(portal_mitglieder)))

    portal_nach_fg = {a.fg: a for a in portal_mitglieder if a.fg}
    portal_lax = set()
    for a in accounts:
        for mail in {a.email, a.zusatz_email1, a.zusatz_email2}:
            if mail:
                portal_lax.add(_lax(a.vorname, a.nachname, mail))
    fairgate_fgs = set()
    unbekannt_fgs = set()          # FGs mit unbekannter Kategorie: Austritt unterdrücken
    unbekannte_kat_zaehler = {}    # Kategoriename -> Anzahl betroffener Kontakte
    regel_namen = {k.name for k in regeln.kategorien}
    e.kategorien = {"pflichtig": {}, "nicht_pflichtig": {}, "unbekannt": {}}

    for k in kontakte:
        regel = regeln.fuer_kategorie(k.kategorie)
        topf = ("pflichtig" if regel else "nicht_pflichtig" if k.kategorie in regel_namen else "unbekannt")
        e.kategorien[topf][k.kategorie] = e.kategorien[topf].get(k.kategorie, 0) + 1
        if regel is None:
            if k.kategorie not in regel_namen:
                # Kategorie steht in KEINER Regel (weder pflichtig noch nicht-pflichtig):
                # vermutlich ein Regel-Lücke, keine stillen Austritte/Neueintritte daraus ableiten.
                unbekannte_kat_zaehler[k.kategorie] = unbekannte_kat_zaehler.get(k.kategorie, 0) + 1
                if k.fg:
                    unbekannt_fgs.add(k.fg)
            continue                             # nicht helferpflichtig (oder unbekannt)
        fairgate_fgs.add(k.fg)
        alter = _alter(k.geburtsdatum, heute)
        if alter is None and k.geburtsdatum:
            e.klaerliste.append(
                f"{k.vorname} {k.nachname} ({k.fg}): Geburtsdatum «{k.geburtsdatum}» nicht "
                "lesbar (erwartet JJJJ-MM-TT oder TT.MM.JJJJ) — in Fairgate korrigieren.")
            continue
        konto = portal_nach_fg.get(k.fg)
        if konto is None:
            mail = _ziel_email(k, regeln, heute)
            if not mail:
                e.klaerliste.append(f"{k.vorname} {k.nachname} ({k.fg}): keine erreichbare "
                                    "E-Mail (weder eigene noch Haushalt) — in Fairgate nachtragen.")
                continue
            # FG-Nachtrag (Spez. 6.3/D4, konservativ): exakter, case-sensitiver
            # Tripel-Treffer gegen einen Mitglieds-Portal-Account ohne FG-Nummer. Nur bei
            # leerer Bemerkung automatisch nachtragen — sonst würde der Import sie überschreiben.
            # Zusätzlich für UNKLASSIFIZIERTE Accounts (nur Funktionsgruppen, kein Marker — typisch:
            # von Hand im Portal angelegtes Mitglied): FG nachtragen UND Gruppe «Mitglied» ergänzen.
            fg_nachtrag = next((a for a in accounts if not a.fg
                                and a.typ in (Typ.MITGLIED, Typ.UNKLASSIFIZIERT)
                                and a.vorname == k.vorname and a.nachname == k.nachname
                                and mail in ({a.email, a.zusatz_email1, a.zusatz_email2} - {""})),
                               None)
            if fg_nachtrag is not None:
                if not fg_nachtrag.bemerkung:
                    gruppe = ("" if fg_nachtrag.typ == Typ.MITGLIED
                              else _gruppen_vereinigt(fg_nachtrag, regel.portal_gruppe))
                    e.korrekturen.append(ImportZeile(
                        vorname=fg_nachtrag.vorname, nachname=fg_nachtrag.nachname,
                        email=fg_nachtrag.email, zielwert=str(regel.zielwert), bemerkungen=k.fg,
                        gruppe=gruppe))
                else:
                    e.klaerliste.append(
                        f"{k.vorname} {k.nachname} ({k.fg}): FG-Nachtrag von Hand — "
                        "Bemerkungsfeld ist belegt, der Import würde es überschreiben.")
                continue
            # Namens-Übereinstimmung ohne Mail-Treffer: eigener Fall vom FG-Nachtrag, da die
            # Mail abweicht (z. B. neue Eltern-Mail) — nicht automatisch verknüpfen, von Hand klären.
            namens_match = next((a for a in accounts if not a.fg
                                 and a.vorname == k.vorname and a.nachname == k.nachname), None)
            if namens_match is not None:
                e.duplikat_warnungen.append(
                    f"{k.vorname} {k.nachname} ({k.fg}): namensgleicher Portal-Account ohne FG "
                    "mit anderer E-Mail — von Hand prüfen (FG-Nachtrag/Eltern-Mail?).")
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
            # E-Mail-Abgleich, tolerant: Die Portal-Adresse ist die vom Mitglied selbst
            # gewählte Login-Adresse. Sie gilt als stimmig, wenn sie IRGENDEINER Adresse des
            # Fairgate-Kontakts entspricht (eigene, Eltern, weitere; Gross/Klein egal). Die
            # Altersregel entscheidet nur bei Neueintritten, welche Adresse verwendet wird.
            mail = _ziel_email(k, regeln, heute)
            portal_mails = {m.lower() for m in (konto.email, konto.zusatz_email1, konto.zusatz_email2) if m}
            if mail and not (portal_mails & _fairgate_adressen(k)):
                if regeln.email_abweichung == "handarbeit":
                    e.handarbeit.append(HandarbeitsFall(
                        "schluessel", konto.anzeigename, k.fg,
                        f"E-Mail in Fairgate: {mail} — im Portal: {konto.email}. Zuerst im Portal "
                        "nachführen, sonst legt ein Import mit der neuen Adresse ein Duplikat an.",
                        helper_id=konto.id))
                else:
                    e.kontakt_abweichungen.append({
                        "name": konto.anzeigename, "fg": k.fg, "helper_id": konto.id,
                        "portal_mail": konto.email, "fairgate_mail": mail})
            # Feld-Leerung: Fairgate hat das Feld geleert, Portal noch nicht — leere
            # Zellen überschreiben im Import nichts, also nur von Hand (Spez. 6.3).
            if not k.telefon and konto.telefon:
                e.handarbeit.append(HandarbeitsFall(
                    "leerung", konto.anzeigename, k.fg,
                    f"Telefon in Fairgate geleert (Portal: {konto.telefon}) — Feld im Portal "
                    "von Hand leeren, der Import kann das nicht.", helper_id=konto.id))
            # Wert-Korrekturen (Update-Import, Tripel aus dem Portal, Gruppen-Spalte leer!)
            # Bemerkungen bleiben leer: eine leere Zelle überschreibt im Import nichts, das
            # Tripel (Vorname/Nachname/E-Mail) ist der Match-Schlüssel (Spez. 6.3).
            aenderungen = {}
            if konto.zielwert != regel.zielwert:
                aenderungen["zielwert"] = str(regel.zielwert)
            if k.telefon and k.telefon != konto.telefon:
                aenderungen["telefon"] = k.telefon
            if aenderungen:
                e.korrekturen.append(ImportZeile(
                    vorname=konto.vorname, nachname=konto.nachname, email=konto.email,
                    bemerkungen="", **aenderungen))

    # Austritte: Portal-Mitglied, dessen FG in Fairgate (pflichtige Kategorien) fehlt.
    # FGs mit unbekannter Kategorie werden ausgenommen — dort ist unklar, ob der Kontakt
    # wirklich ausgetreten oder nur eine Regel-Lücke betroffen ist (siehe unbekannt_fgs oben).
    for fg, konto in sorted(portal_nach_fg.items()):
        if fg not in fairgate_fgs and fg not in unbekannt_fgs:
            e.handarbeit.append(HandarbeitsFall(
                "austritt", konto.anzeigename, fg,
                "In Fairgate nicht mehr als pflichtiges Mitglied geführt — im Portal "
                "deaktivieren (der Import löscht nichts).", helper_id=konto.id))

    # Zweitaccounts/Freiwillige mit Zielwert ≠ 0 → Korrektur auf 0 (Spez. D2/D7).
    # Bemerkungen bleiben leer (siehe oben) — eine leere Zelle überschreibt nichts.
    for a in accounts:
        if a.typ in (Typ.ZWEITACCOUNT, Typ.FREIWILLIG) and a.zielwert != 0:
            e.korrekturen.append(ImportZeile(
                vorname=a.vorname, nachname=a.nachname, email=a.email,
                zielwert="0", bemerkungen=""))

    for kategorie in sorted(unbekannte_kat_zaehler):
        n = unbekannte_kat_zaehler[kategorie]
        e.unbekannte_kategorien.append(
            f"Unbekannte Fairgate-Kategorie ‹{kategorie}› bei {n} Kontakten — Regeln prüfen, "
            "diese Kontakte wurden NICHT abgeglichen.")

    teile = []
    if e.neueintritte: teile.append(f"{len(e.neueintritte)} Neueintritte")
    austritte = [h for h in e.handarbeit if h.art == "austritt"]
    if austritte: teile.append(f"{len(austritte)} Austritte")
    if e.korrekturen: teile.append(f"{len(e.korrekturen)} Korrekturen")
    e.zusammenfassung = ((", ".join(teile) if teile else "Alles synchron")
                         + f" bei {e.geprueft} geprüften Mitgliedern.")
    return e
