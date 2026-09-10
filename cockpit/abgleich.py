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
    art: str      # "austritt" | "schluessel"
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


def _einsatz_text(a):
    return f"{a.num_ok} geleistet, {a.num_confirmed} zugesagt"


ENTSCHEIDUNGSHILFE = ("Entscheidungshilfe: Steht in der E-Mail des Accounts ohne FG-Nummer der eigene Vorname, "
                      "ist es dieselbe Person mit neuer Adresse. Steht ein anderer Vorname zum gleichen Nachnamen "
                      "(Familienadresse), ist es der Zweitaccount eines Elternteils.")


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

    def klaer(titel, fakten, optionen, wo="Portal", helper_id=None, fg=""):
        """Klärfall = eine Entscheidung, die nur ein Mensch treffen kann. Immer mit: worum es
        geht (Fakten), was bei welcher Antwort zu tun ist (Optionen), und wo (Portal/Fairgate)."""
        e.klaerliste.append({"titel": titel, "fakten": list(fakten), "optionen": list(optionen),
                             "wo": wo, "helper_id": helper_id, "fg": fg})

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
                # Telefon nur im Portal, nicht in Fairgate: bewusst KEINE Massnahme (Entscheid 10.09.2026)
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
            # Fall H: FG nicht (mehr) in Fairgate → Austritt. Das Portal kennt nur «Helfer:in
            # löschen» (unwiderruflich, kein Deaktivieren) — das kann nur der Mensch.
            if a.typ == Typ.MITGLIED:
                treffer = (set().union(*(mail_fgs.get(m, set()) for m in _portal_adressen(a)))
                           | name_fgs.get(_name(a.vorname, a.nachname), set()))
                fg_zugeordnet.update(treffer)          # kein Neueintritt für die «neue» FG
                teile = []
                if treffer:
                    teile.append(f"Achtung: E-Mail/Name passen zu {', '.join(sorted(treffer))} — "
                                 "FG-Nummer geändert? Dann im Portal die Bemerkung anpassen statt löschen.")
                offen = a.num_confirmed + a.num_reserved + a.num_unconfirmed
                if offen:
                    teile.append(f"Noch {offen} offene Einsätze — vor dem Löschen klären, sonst bleiben "
                                 "die Schichten unbesetzt.")
                if not teile:
                    teile.append("Keine offenen Einsätze.")
                e.handarbeit.append(HandarbeitsFall("austritt", a.anzeigename, a.fg, " ".join(teile),
                                                    helper_id=a.id))
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
                        haupt = portal_nach_fg[fg0]
                        klaer(f"{a.anzeigename}: Zweitaccount von {fg0} — FG-Nummer von Hand eintragen",
                              [f"Portal-Account «{a.anzeigename}» hat E-Mail und Name wie Fairgate-Kontakt {fg0}",
                               f"Zur FG-Nummer {fg0} gibt es bereits den Mitglieds-Account «{haupt.anzeigename}» — dieser Account hier ist also ein Zweitaccount",
                               f"Das Bemerkungsfeld ist belegt («{a.bemerkung}»), darum kann der Import die FG-Nummer nicht eintragen"],
                              [f"Im Portal bei «{a.anzeigename}»: Bemerkung um «{fg0}» ergänzen — Zielwert 0 und Gruppe «Freiwillige» setzt danach der nächste Abgleich automatisch"],
                              helper_id=a.id, fg=fg0)
                    else:
                        e.korrekturen.append(ImportZeile(
                            vorname=a.vorname, nachname=a.nachname, email=a.email,
                            bemerkungen=fg0, zielwert="0" if a.zielwert != 0 else "",
                            gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)),
                            grund=f"Zweitaccount von {fg0}: FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»"))
                else:
                    # FG-Nachtrag: dieser Account ist das Mitglied
                    if a.bemerkung:
                        klaer(f"{a.anzeigename}: ist Mitglied {fg0} — FG-Nummer von Hand eintragen",
                              [f"Portal-Account «{a.anzeigename}» hat E-Mail und Name wie Fairgate-Kontakt {fg0}, aber keine FG-Nummer",
                               f"Das Bemerkungsfeld ist belegt («{a.bemerkung}»), darum kann der Import die FG-Nummer nicht eintragen"],
                              [f"Im Portal bei «{a.anzeigename}»: Bemerkung um «{fg0}» ergänzen — Zielwert und Gruppe «Mitglied» setzt danach der nächste Abgleich automatisch"],
                              helper_id=a.id, fg=fg0)
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
                # Fall C: E-Mail bekannt, Name nicht.
                mit_account = sorted(f for f in per_mail if f in fg_mit_mitgliedsaccount)
                if mit_account:
                    # C1: das Mitglied hat bereits einen eigenen Account → dieser hier (anderer Name,
                    # gleiche Familien-E-Mail) ist eindeutig ein Zweitaccount, z. B. ein Elternteil.
                    fg0 = mit_account[0]
                    haupt = portal_nach_fg[fg0]
                    if a.bemerkung:
                        klaer(f"{a.anzeigename}: Zweitaccount von {fg0} — FG-Nummer von Hand eintragen",
                              [f"Portal-Account «{a.anzeigename}» verwendet dieselbe E-Mail wie Fairgate-Kontakt {fg0} («{haupt.anzeigename}»)",
                               f"«{haupt.anzeigename}» hat bereits einen eigenen Mitglieds-Account — «{a.anzeigename}» ist also ein Zweitaccount (z. B. Elternteil)",
                               f"Das Bemerkungsfeld ist belegt («{a.bemerkung}»), darum kann der Import die FG-Nummer nicht eintragen"],
                              [f"Im Portal bei «{a.anzeigename}»: Bemerkung um «{fg0}» ergänzen — Zielwert 0 und Gruppe «Freiwillige» setzt danach der nächste Abgleich automatisch"],
                              helper_id=a.id, fg=fg0)
                    else:
                        e.korrekturen.append(ImportZeile(
                            vorname=a.vorname, nachname=a.nachname, email=a.email,
                            bemerkungen=fg0, zielwert="0" if a.zielwert != 0 else "",
                            gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)),
                            grund=f"Zweitaccount von {fg0} («{haupt.anzeigename}», gleiche E-Mail): FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»"))
                    fg_zugeordnet.add(fg0)
                else:
                    # C2: der Fairgate-Kontakt hat noch keinen Account — gleiche Person (anders
                    # geschrieben) oder Elternteil? Das muss ein Mensch entscheiden.
                    fg0 = sorted(per_mail)[0]
                    k = pflichtig[fg0]
                    kname = f"{k.vorname} {k.nachname}"
                    klaer(f"{a.anzeigename}: gleiche E-Mail wie Fairgate-Kontakt «{kname}» ({fg0})",
                          [f"Portal-Account «{a.anzeigename}» (ohne FG-Nummer) verwendet {a.email}",
                           f"Diese E-Mail steht in Fairgate bei «{kname}» ({fg0}) — und «{kname}» hat noch keinen Portal-Account",
                           f"Name im Portal: «{a.anzeigename}» · Name in Fairgate: «{kname}»"],
                          [f"Gleiche Person, nur anders geschrieben → im Portal bei «{a.anzeigename}» Vor- und Nachname wie in Fairgate schreiben; der nächste Abgleich trägt {fg0} dann automatisch nach",
                           f"Elternteil von «{kname}» → im Portal bei «{a.anzeigename}» Bemerkung «{fg0}» eintragen, Zielwert 0, Gruppe «Freiwillige»; für «{kname}» legt der nächste Abgleich einen eigenen Account an"],
                          helper_id=a.id, fg=fg0)
                    fg_zugeordnet.update(per_mail)
            elif per_name and not (portal_nach_fg.get(sorted(per_name)[0]) and a.typ == Typ.FREIWILLIG
                                   and a.zielwert == 0 and not hat_mitglied):
                # Fall E: Name bekannt, E-Mail nicht — Neuregistrierung mit neuer Adresse oder
                # Zweitaccount unter dem Namen des Kinds? Ein bereits als Freiwillige(r) mit
                # Zielwert 0 geführter Namensvetter (Mitglied hat eigenen Account) gilt als erledigt.
                fg0 = sorted(per_name)[0]
                k = pflichtig[fg0]
                alt = portal_nach_fg.get(fg0)
                fakten = [f"Portal-Account «{a.anzeigename}» (ohne FG-Nummer) mit E-Mail {a.email} · {_einsatz_text(a)}",
                          f"Fairgate-Kontakt «{k.vorname} {k.nachname}» ({fg0}) mit "
                          + (f"E-Mail {k.email or k.eltern_email}" if (k.email or k.eltern_email) else "keiner E-Mail")
                          + (f" · Telefon {k.telefon}" if k.telefon else "")]
                if alt:
                    fakten.append(f"Zur FG-Nummer {fg0} gibt es bereits den Account «{alt.anzeigename}» "
                                  f"({alt.email} · {_einsatz_text(alt)})")
                    fakten.append(ENTSCHEIDUNGSHILFE)
                    optionen = [f"Zweitaccount (Elternteil) → beide Accounts bleiben; im Portal bei «{a.anzeigename}» ({a.email}) "
                                f"Bemerkung «{fg0}» eintragen, Gruppe «Freiwillige» statt «Mitglied», Zielwert 0 — ab dann zählen seine Einsätze dem Mitglied",
                                f"Dieselbe Person mit neuer E-Mail → Einsätze von «{a.anzeigename}» ({a.email}) auf den Account "
                                f"«{alt.anzeigename}» ({alt.email}) umhängen (Portal: Event öffnen, Einsatz bearbeiten, Person wechseln); "
                                f"dort die E-Mail auf {a.email} ändern; danach den Account ohne FG-Nummer löschen (unwiderruflich)",
                                f"Andere Person (nur Namensgleichheit) → im Portal bei «{a.anzeigename}» Gruppe «Freiwillige», Zielwert 0; "
                                "dann ist der Fall erledigt"]
                else:
                    fakten.append("Der Fairgate-Kontakt hat sonst keinen Portal-Account — vermutlich dieselbe Person "
                                  "mit anderer E-Mail, sonst eine Namensgleichheit")
                    optionen = [f"Gleiche Person → im Portal bei «{a.anzeigename}» Bemerkung «{fg0}» eintragen; "
                                "Zielwert und Gruppe «Mitglied» setzt danach der nächste Abgleich automatisch",
                                f"Andere Person (nur Namensgleichheit) → nichts tun; der nächste Abgleich legt für {fg0} "
                                "einen eigenen Account an"
                                + (f" (unsicher? anrufen: {k.telefon})" if k.telefon else "")]
                klaer(f"{a.anzeigename}: gleicher Name wie Fairgate-Kontakt {fg0}, aber andere E-Mail",
                      fakten, optionen, helper_id=a.id, fg=fg0)
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
                    mitglieder = [f"«{pflichtig[f].vorname} {pflichtig[f].nachname}» ({f})" for f in sorted(familie)]
                    n = _einsaetze(a)
                    e.hinweise.append({
                        "titel": f"{a.anzeigename}: gleicher Nachname wie Mitglied {', '.join(sorted(familie))} — Elternteil?",
                        "fakten": [f"Portal-Account «{a.anzeigename}» ({a.email}) · {_einsatz_text(a)}",
                                   f"Gleicher Nachname in Fairgate: {', '.join(mitglieder)}",
                                   "Der Import macht daraus Freiwillige(r) mit Zielwert 0 — das stimmt in beiden Fällen"],
                        "optionen": [("Elternteil oder Zweitaccount → im Portal in die Bemerkung «" + sorted(familie)[0]
                                      + "» eintragen (vor oder nach dem Import); ab dann zählen die Einsätze dem Mitglied"
                                      if len(familie) == 1 else
                                      "Elternteil oder Zweitaccount → im Portal in die Bemerkung die FG-Nummer des Kinds eintragen "
                                      f"({' oder '.join(mitglieder)}); bei Geschwistern eine wählen — die Einsätze zählen dann diesem Kind"),
                                     "Andere Person → nichts tun"],
                        "wo": "Portal", "helper_id": a.id, "fg": sorted(familie)[0], "einsaetze": n})
            # sonst: echte(r) Freiwillige(r) — nichts zu tun

    # ---- Phase 2: Fairgate-Kontakte ohne Portal-Account → Neueintritte ------------------
    for fg, k in pflichtig.items():
        if fg in portal_nach_fg or fg in fg_zugeordnet:
            continue
        regel = regeln.fuer_kategorie(k.kategorie)
        alter = _alter(k.geburtsdatum, heute)
        if alter is None and k.geburtsdatum:
            klaer(f"{k.vorname} {k.nachname} ({fg}): Geburtsdatum in Fairgate nicht lesbar",
                  [f"Fairgate-Kontakt {fg} hat das Geburtsdatum «{k.geburtsdatum}» — erwartet JJJJ-MM-TT oder TT.MM.JJJJ",
                   "Ohne Alter kann das Cockpit nicht entscheiden, ob die eigene oder die Eltern-E-Mail gilt"],
                  ["In Fairgate das Geburtsdatum korrigieren; der nächste Abgleich legt den Account dann an"],
                  wo="Fairgate", fg=fg)
            continue
        mail = _ziel_email(k, regeln, heute)
        if not mail:
            klaer(f"{k.vorname} {k.nachname} ({fg}): keine E-Mail in Fairgate",
                  [f"Fairgate-Kontakt {fg} hat weder eine eigene noch eine Eltern-E-Mail",
                   "Ohne E-Mail kann im Portal kein Account angelegt werden"]
                  + ([f"Telefon in Fairgate: {k.telefon}"] if k.telefon else ["Auch keine Telefonnummer in Fairgate"]),
                  [(f"Anrufen ({k.telefon}) und die E-Mail erfragen → " if k.telefon else "E-Mail beschaffen → ")
                   + "in Fairgate eintragen (eigene oder Eltern); der nächste Abgleich legt den Account dann an"],
                  wo="Fairgate", fg=fg)
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

    # Hinweise mit Einsätzen zuerst — nur dort geht dem Mitglied etwas verloren
    e.hinweise.sort(key=lambda h: -(h.get("einsaetze", 0) if isinstance(h, dict) else 0))

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
