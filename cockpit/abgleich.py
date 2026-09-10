"""Quartals-Abgleich Fairgate → Portal (Spez. Kap. 6.3, Neufassung 10.09.2026).

Grundidee: Erst mit BEIDEN Seiten — Portal-Bestand und Fairgate-Export — lässt sich pro
Account sagen, was er sein sollte (Soll-Zustand): Mitglied, Zweitaccount, Freiwillige(r),
Unbekannt oder Austritt. Aus Soll- und Ist-Zustand folgt die Massnahme. Alles, was der
Portal-Import kann (Zielwert, Gruppenliste, FG-Nummer in eine leere Bemerkung), wird zur
Import-Zeile mit Begründung; nur was der Import nicht kann, wird Handarbeit oder Klärfall.

Liest nur, schreibt nie. Sicherheitsregeln: Bemerkungen werden nur beschrieben, wenn sie leer
sind; die Gruppen-Spalte (ersetzt im Portal die ganze Liste!) wird nur befüllt, wenn sich die
Marker-Gruppen ändern — und dann immer mit der vollständigen Zielliste.
"""
import datetime
from dataclasses import dataclass, field
from .model import Typ, GRUPPE_MITGLIED, GRUPPE_FREIWILLIGE, GRUPPE_UNBEKANNTE

MARKER = (GRUPPE_MITGLIED, GRUPPE_FREIWILLIGE, GRUPPE_UNBEKANNTE)


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
    grund: str = ""           # nicht Teil der 11 Import-Spalten — nur für die Vorschau


@dataclass
class HandarbeitsFall:
    art: str      # "austritt" | "schluessel" | "leerung"
    name: str
    fg: str
    detail: str
    helper_id: int = None


@dataclass
class AbgleichErgebnis:
    neueintritte: list = field(default_factory=list)
    korrekturen: list = field(default_factory=list)
    handarbeit: list = field(default_factory=list)
    klaerliste: list = field(default_factory=list)
    duplikat_warnungen: list = field(default_factory=list)
    unbekannte_kategorien: list = field(default_factory=list)
    kontakt_abweichungen: list = field(default_factory=list)
    hinweise: list = field(default_factory=list)          # Info, keine Handarbeit (z. B. möglicher Zweitaccount)
    kategorien: dict = field(default_factory=dict)
    zusammenfassung: str = ""
    geprueft: int = 0


# ------------------------------------------------------------------ Hilfsfunktionen ----

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


def _fairgate_adressen(k):
    return {m.strip().lower() for m in (list(k.alle_emails) + [k.email, k.eltern_email]) if m}


def _portal_adressen(a):
    return {m.strip().lower() for m in (a.email, a.zusatz_email1, a.zusatz_email2) if m}


def _name(vn, nn):
    return (vn.strip().lower(), nn.strip().lower())


def _zielgruppen(konto, hinzu=(), weg=()):
    """Vollständige Gruppenliste nach Änderung der Marker; Funktionsgruppen bleiben.
    Liefert "" wenn sich nichts ändert (leere Zelle = Import lässt Gruppen unangetastet)."""
    neu = [g for g in konto.gruppen if g not in weg]
    for g in hinzu:
        if g not in neu:
            neu.append(g)
    return ", ".join(neu) if neu != list(konto.gruppen) else ""


def _einsaetze(a):
    return a.num_ok + a.num_confirmed + a.num_reserved + a.num_unconfirmed + (1 if a.ist_wert > 0 else 0)


# ------------------------------------------------------------------ Abgleich ----

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

    # ---- Fairgate indexieren -------------------------------------------------------
    regel_namen = {k.name for k in regeln.kategorien}
    e.kategorien = {"pflichtig": {}, "nicht_pflichtig": {}, "unbekannt": {}}
    pflichtig = {}            # fg -> kontakt (helferpflichtige Kategorie)
    nicht_pflichtig_fgs = set()
    unbekannt_fgs = set()
    unbekannte_kat_zaehler = {}
    for k in kontakte:
        regel = regeln.fuer_kategorie(k.kategorie)
        topf = "pflichtig" if regel else "nicht_pflichtig" if k.kategorie in regel_namen else "unbekannt"
        e.kategorien[topf][k.kategorie] = e.kategorien[topf].get(k.kategorie, 0) + 1
        if regel:
            pflichtig[k.fg] = k
        elif k.kategorie in regel_namen:
            nicht_pflichtig_fgs.add(k.fg)
        else:
            unbekannte_kat_zaehler[k.kategorie] = unbekannte_kat_zaehler.get(k.kategorie, 0) + 1
            unbekannt_fgs.add(k.fg)
    mail_fgs, name_fgs, nachname_fgs = {}, {}, {}
    for fg, k in pflichtig.items():
        for m in _fairgate_adressen(k):
            mail_fgs.setdefault(m, set()).add(fg)
        name_fgs.setdefault(_name(k.vorname, k.nachname), set()).add(fg)
        nachname_fgs.setdefault(k.nachname.strip().lower(), set()).add(fg)

    # ---- Portal indexieren ---------------------------------------------------------
    portal_nach_fg = {a.fg: a for a in portal_mitglieder if a.fg}      # Mitglieds-Accounts
    fg_mit_mitgliedsaccount = set(portal_nach_fg)
    fg_zugeordnet = set()     # Fairgate-FGs, die über einen FG-losen Account abgedeckt werden

    def klaer(text):
        e.klaerliste.append(text)

    def korrektur(a, grund, **felder):
        if not any(felder.values()):
            return
        e.korrekturen.append(ImportZeile(vorname=a.vorname, nachname=a.nachname, email=a.email,
                                         bemerkungen="", grund=grund, **felder))

    # ---- Phase 1: jeder Portal-Account → Soll-Zustand → Massnahme ----------------------
    for a in accounts:
        hat_mitglied = GRUPPE_MITGLIED in a.gruppen
        if a.fg and a.fg in pflichtig:
            k = pflichtig[a.fg]
            regel = regeln.fuer_kategorie(k.kategorie)
            if hat_mitglied:
                # Fall A: bekanntes Mitglied — Werte nachführen, überzählige Marker entfernen
                felder = {}
                if a.zielwert != regel.zielwert:
                    felder["zielwert"] = str(regel.zielwert)
                if k.telefon and k.telefon != a.telefon:
                    felder["telefon"] = k.telefon
                felder["gruppe"] = _zielgruppen(a, weg=(GRUPPE_FREIWILLIGE, GRUPPE_UNBEKANNTE))
                grund = "Mitglied: " + ", ".join(
                    [t for t, ok in (("Zielwert nachführen", "zielwert" in felder),
                                     ("Telefon nachführen", "telefon" in felder),
                                     ("überzählige Gruppe «Freiwillige/Unbekannte» entfernen", bool(felder["gruppe"]))) if ok])
                korrektur(a, grund, **felder)
                if not k.telefon and a.telefon:
                    e.handarbeit.append(HandarbeitsFall(
                        "leerung", a.anzeigename, a.fg,
                        f"Telefon in Fairgate geleert (Portal: {a.telefon}) — Feld im Portal von "
                        "Hand leeren, der Import kann das nicht.", helper_id=a.id))
                _email_pruefen(e, a, k, regeln, heute)
            elif a.fg in fg_mit_mitgliedsaccount:
                # Fall F2: Zweitaccount eines bestehenden Mitglieds — Zielwert 0, Marker «Freiwillige»
                korrektur(a, "Zweitaccount: Zielwert 0, Gruppe «Freiwillige»",
                          zielwert="0" if a.zielwert != 0 else "",
                          gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_UNBEKANNTE,)))
            else:
                # Fall F1: FG-Nummer da, aber kein «Mitglied»-Marker und kein anderer Mitglieds-Account
                # → dieser Account IST das Mitglied
                korrektur(a, "Ist das Mitglied zu dieser FG-Nummer: Gruppe «Mitglied», Zielwert setzen",
                          zielwert=str(regel.zielwert) if a.zielwert != regel.zielwert else "",
                          gruppe=_zielgruppen(a, hinzu=(GRUPPE_MITGLIED,), weg=(GRUPPE_FREIWILLIGE, GRUPPE_UNBEKANNTE)))
                fg_mit_mitgliedsaccount.add(a.fg)
                portal_nach_fg[a.fg] = a
        elif a.fg and a.fg in nicht_pflichtig_fgs:
            # Kategorie ohne Helferpflicht (z. B. Passivmitglied): kein Zielwert
            korrektur(a, "Kategorie ohne Helferpflicht: Zielwert 0",
                      zielwert="0" if a.zielwert != 0 else "")
        elif a.fg and a.fg in unbekannt_fgs:
            pass                                       # Regel-Lücke: nichts ableiten (Warnung unten)
        elif a.fg:
            # Fall H: FG nicht (mehr) in Fairgate → Austritt. Deaktivieren kann nur der Mensch.
            if a.typ == Typ.MITGLIED:
                treffer = (set().union(*(mail_fgs.get(m, set()) for m in _portal_adressen(a)))
                           | name_fgs.get(_name(a.vorname, a.nachname), set()))
                hinweis = (f" Achtung: E-Mail/Name passen zu {', '.join(sorted(treffer))} — "
                           "FG-Nummer geändert? Dann Bemerkung im Portal anpassen statt deaktivieren."
                           if treffer else "")
                fg_zugeordnet.update(treffer)          # kein Neueintritt für die «neue» FG
                e.handarbeit.append(HandarbeitsFall(
                    "austritt", a.anzeigename, a.fg,
                    "In Fairgate nicht mehr als pflichtiges Mitglied geführt — im Portal "
                    "deaktivieren (der Import löscht nichts)." + hinweis, helper_id=a.id))
            else:
                korrektur(a, "Zweitaccount eines ausgetretenen Mitglieds: Zielwert 0",
                          zielwert="0" if a.zielwert != 0 else "")
        else:
            # ---- ohne FG-Nummer: wer ist das? ----
            mails = _portal_adressen(a)
            per_mail = set().union(*(mail_fgs.get(m, set()) for m in mails)) if mails else set()
            per_name = name_fgs.get(_name(a.vorname, a.nachname), set())
            exakt = per_mail & per_name
            if exakt:
                fg0 = sorted(exakt)[0]
                k = pflichtig[fg0]
                regel = regeln.fuer_kategorie(k.kategorie)
                if fg0 in fg_mit_mitgliedsaccount:
                    # Fall D: Mitglied hat schon einen Account → dieser ist ein Zweitaccount
                    if a.bemerkung:
                        klaer(f"{a.anzeigename}: ist ein Zweitaccount von {fg0} — Bemerkungsfeld ist "
                              "belegt, FG-Nummer von Hand eintragen (Import würde es überschreiben).")
                    else:
                        e.korrekturen.append(ImportZeile(
                            vorname=a.vorname, nachname=a.nachname, email=a.email,
                            bemerkungen=fg0, zielwert="0" if a.zielwert != 0 else "",
                            gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)),
                            grund=f"Zweitaccount von {fg0}: FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»"))
                else:
                    # FG-Nachtrag: dieser Account ist das Mitglied
                    if a.bemerkung:
                        klaer(f"{a.anzeigename}: ist Mitglied {fg0} — Bemerkungsfeld ist belegt, "
                              "FG-Nummer von Hand eintragen (Import würde es überschreiben).")
                    else:
                        e.korrekturen.append(ImportZeile(
                            vorname=a.vorname, nachname=a.nachname, email=a.email,
                            bemerkungen=fg0, zielwert=str(regel.zielwert) if a.zielwert != regel.zielwert else "",
                            gruppe=_zielgruppen(a, hinzu=(GRUPPE_MITGLIED,), weg=(GRUPPE_FREIWILLIGE, GRUPPE_UNBEKANNTE)),
                            grund=f"Mitglied {fg0} ohne FG-Nummer: FG eintragen, Gruppe «Mitglied», Zielwert setzen"))
                    fg_mit_mitgliedsaccount.add(fg0)
                    portal_nach_fg[fg0] = a
                fg_zugeordnet.add(fg0)
            elif per_mail:
                # Fall C: E-Mail bekannt, Name nicht — gleiche Person oder Elternteil?
                fgs = ", ".join(sorted(per_mail))
                klaer(f"{a.anzeigename}: E-Mail gehört zu Fairgate-Kontakt {fgs} "
                      f"({', '.join(pflichtig[f].vorname + ' ' + pflichtig[f].nachname for f in sorted(per_mail))}). "
                      "Gleiche Person mit anderer Schreibweise → FG-Nummer nachtragen und Gruppe «Mitglied»; "
                      "Elternteil → FG-Nummer nachtragen, Zielwert 0, Gruppe «Freiwillige» (Zweitaccount).")
                fg_zugeordnet.update(per_mail)
            elif per_name:
                # Fall E: Name bekannt, E-Mail nicht — Neuregistrierung mit neuer Adresse?
                fgs = ", ".join(sorted(per_name))
                klaer(f"{a.anzeigename}: gleicher Name wie Fairgate-Kontakt {fgs}, aber andere E-Mail — "
                      "vermutlich Neuregistrierung. Im Portal prüfen und ggf. FG-Nummer nachtragen "
                      "oder Accounts zusammenführen.")
                fg_zugeordnet.update(per_name)
            elif a.typ == Typ.UNBEKANNT:
                # Fall I: Unbekannte mit Einsätzen → Freiwillige (Vereinsregel, automatisiert)
                if _einsaetze(a):
                    korrektur(a, "Unbekannt mit Einsätzen: wird Freiwillige(r)",
                              zielwert="0" if a.zielwert != 0 else "",
                              gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_UNBEKANNTE, GRUPPE_MITGLIED)))
            elif hat_mitglied or a.zielwert != 0 or a.typ == Typ.UNKLASSIFIZIERT:
                # Fall B: sieht aus wie ein Mitglied, ist aber in Fairgate nirgends zu finden
                korrektur(a, "Kein Mitglied in Fairgate (weder FG, E-Mail noch Name): Freiwillige(r), Zielwert 0",
                          zielwert="0" if a.zielwert != 0 else "",
                          gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)))
                familie = nachname_fgs.get(a.nachname.strip().lower(), set()) & fg_mit_mitgliedsaccount
                if familie:
                    e.hinweise.append(f"{a.anzeigename}: wird Freiwillige(r) — gleicher Nachname wie Mitglied "
                                      f"{', '.join(sorted(familie))}. Falls Elternteil/Zweitaccount: FG-Nummer im "
                                      "Portal in die Bemerkung eintragen, dann zählen die Einsätze dem Mitglied.")
            # sonst: echte(r) Freiwillige(r) — nichts zu tun

    # ---- Phase 2: Fairgate-Kontakte ohne Portal-Account → Neueintritte ------------------
    for fg, k in pflichtig.items():
        if fg in portal_nach_fg or fg in fg_zugeordnet:
            continue
        regel = regeln.fuer_kategorie(k.kategorie)
        alter = _alter(k.geburtsdatum, heute)
        if alter is None and k.geburtsdatum:
            klaer(f"{k.vorname} {k.nachname} ({fg}): Geburtsdatum «{k.geburtsdatum}» nicht lesbar "
                  "(erwartet JJJJ-MM-TT oder TT.MM.JJJJ) — in Fairgate korrigieren.")
            continue
        mail = _ziel_email(k, regeln, heute)
        if not mail:
            klaer(f"{k.vorname} {k.nachname} ({fg}): keine erreichbare E-Mail (weder eigene noch "
                  "Haushalt) — in Fairgate nachtragen.")
            continue
        e.neueintritte.append(ImportZeile(
            vorname=k.vorname, nachname=k.nachname, email=mail, telefon=k.telefon,
            gruppe=regel.portal_gruppe, geburtsdatum=k.geburtsdatum,
            zielwert=str(regel.zielwert), bemerkungen=fg,
            grund="Neueintritt: in Fairgate, noch kein Portal-Account"))

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


def _email_pruefen(e, a, k, regeln, heute):
    """E-Mail-Abgleich, tolerant: Portal-Adresse gilt als stimmig, wenn sie irgendeiner Adresse
    des Fairgate-Kontakts entspricht. Echte Abweichung → je nach Regel Info oder Handarbeit."""
    mail = _ziel_email(k, regeln, heute)
    if mail and not (_portal_adressen(a) & _fairgate_adressen(k)):
        if regeln.email_abweichung == "handarbeit":
            e.handarbeit.append(HandarbeitsFall(
                "schluessel", a.anzeigename, a.fg,
                f"E-Mail in Fairgate: {mail} — im Portal: {a.email}. Zuerst im Portal nachführen, "
                "sonst legt ein Import mit der neuen Adresse ein Duplikat an.", helper_id=a.id))
        else:
            e.kontakt_abweichungen.append({"name": a.anzeigename, "fg": a.fg, "helper_id": a.id,
                                           "portal_mail": a.email, "fairgate_mail": mail})
