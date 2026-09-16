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
    hinweise: list = field(default_factory=list)          # Info, keine Handarbeit
    vorfragen: list = field(default_factory=list)         # müssen VOR der Import-Datei beantwortet werden
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

def gleiche_ab(kontakte, accounts, regeln, heute=None, entscheide=None):
    """entscheide: Antworten auf Vorfragen, {str(helper_id): {"antwort": "zweitaccount"|"andere"|"unklar",
    "fg": "FG-…"}}. Ohne Antwort erzeugt ein möglicher Zweitaccount keine Import-Zeile, sondern eine Vorfrage."""
    heute = heute or datetime.date.today()
    entscheide = entscheide or {}
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

    def fg_nachtrag(a, fg0, zweitaccount, grund, fakten):
        """FG-Nummer per Import in die Bemerkung schreiben — wenn sie leer ist. Sonst setzt der
        Import nur Zielwert und Gruppe, und die FG-Nummer wird ein Klärfall von Hand."""
        regel = regeln.fuer_kategorie(pflichtig[fg0].kategorie)
        if zweitaccount:
            zielwert = "0" if a.zielwert != 0 else ""
            gruppe = _zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE))
        else:
            zielwert = str(regel.zielwert) if a.zielwert != regel.zielwert else ""
            gruppe = _zielgruppen(a, hinzu=(GRUPPE_MITGLIED,), weg=(GRUPPE_FREIWILLIGE, GRUPPE_UNBEKANNTE))
        if a.bemerkung:
            was = "Zielwert 0 und Gruppe «Freiwillige»" if zweitaccount else "Zielwert und Gruppe «Mitglied»"
            klaer(f"{a.anzeigename}: {'Zweitaccount von' if zweitaccount else 'ist Mitglied'} {fg0} — Bemerkung ist belegt, FG-Nummer von Hand eintragen",
                  list(fakten) + [f"Das Bemerkungsfeld ist belegt («{a.bemerkung}»), darum kann der Import die FG-Nummer nicht eintragen"],
                  [f"Im Portal bei «{a.anzeigename}»: Bemerkung um «{fg0}» ergänzen — {was} setzt der Import jetzt schon"],
                  helper_id=a.id, fg=fg0)
            korrektur(a, grund + " — FG-Nummer von Hand, Bemerkung belegt", zielwert=zielwert, gruppe=gruppe)
        else:
            e.korrekturen.append(ImportZeile(vorname=a.vorname, nachname=a.nachname, email=a.email,
                                             bemerkungen=fg0, zielwert=zielwert, gruppe=gruppe, grund=grund))

    def mitglied_gefunden(fg0, a):
        fg_mit_mitgliedsaccount.add(fg0)
        portal_nach_fg[fg0] = a

    def antwort_zu(ent, schluessel, erlaubt, fgs):
        """Gespeicherte Antwort nur übernehmen, wenn sie zu genau dieser Konstellation gehört."""
        if not ent or ent.get("antwort") not in erlaubt:
            return None
        gespeichert = ent.get("schluessel")
        if gespeichert and gespeichert != schluessel:
            return None                                   # Konstellation hat sich geändert → neu fragen
        if not gespeichert and not schluessel.startswith("nachname:"):
            return None                                   # alte Einträge kannten nur Nachnamen-Fälle
        if ent["antwort"] in ("zweitaccount", "elternteil", "gleiche_person", "ersatz") and ent.get("fg") not in fgs:
            return None
        return ent["antwort"]

    def kand(fg):
        k = pflichtig[fg]
        acc = portal_nach_fg.get(fg)
        return {"fg": fg, "name": f"{k.vorname} {k.nachname}", "telefon": k.telefon,
                "portal_account": acc.email if acc else ""}

    def vorfrage(a, fall, schluessel, fgs, frage, fakten, optionen):
        e.vorfragen.append({
            "helper_id": a.id, "name": a.anzeigename, "email": a.email, "gruppen": list(a.gruppen),
            "zielwert": a.zielwert, "einsaetze": _einsaetze(a), "einsatz_text": _einsatz_text(a),
            "bemerkung": a.bemerkung, "fall": fall, "schluessel": schluessel, "frage": frage,
            "fakten": list(fakten), "kandidaten": [kand(f) for f in fgs],
            "optionen": [{"antwort": o[0], "label": o[1], "folge": o[2], "mit_fg": len(o) > 3 and o[3]} for o in optionen]})

    def info(titel, fakten, a):
        return {"titel": titel, "fakten": list(fakten), "optionen": [], "wo": "Portal", "helper_id": a.id, "fg": ""}

    ersatz = {}     # alt.id → (alt, neu, fg): neuer Account ersetzt den alten (Vorfrage «Ersatz»)

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
            ent = entscheide.get(str(a.id)) or {}
            if exakt:
                fg0 = sorted(exakt)[0]
                if fg0 in fg_mit_mitgliedsaccount:
                    # Fall D: Mitglied hat schon einen Account → dieser ist ein Zweitaccount
                    fg_nachtrag(a, fg0, True, f"Zweitaccount von {fg0}: FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»",
                                [f"Portal-Account «{a.anzeigename}» hat E-Mail und Name wie Fairgate-Kontakt {fg0}",
                                 f"Zur FG-Nummer {fg0} gibt es bereits den Mitglieds-Account «{portal_nach_fg[fg0].anzeigename}» — dieser Account hier ist also ein Zweitaccount"])
                else:
                    # FG-Nachtrag: dieser Account ist das Mitglied
                    fg_nachtrag(a, fg0, False, f"Mitglied {fg0} ohne FG-Nummer: FG eintragen, Gruppe «Mitglied», Zielwert setzen",
                                [f"Portal-Account «{a.anzeigename}» hat E-Mail und Name wie Fairgate-Kontakt {fg0}, aber keine FG-Nummer"])
                    mitglied_gefunden(fg0, a)
                fg_zugeordnet.add(fg0)
            elif per_mail:
                # Fall C: E-Mail bekannt, Name nicht.
                mit_account = sorted(f for f in per_mail if f in fg_mit_mitgliedsaccount)
                if mit_account:
                    # C1: das Mitglied hat bereits einen eigenen Account → dieser hier (anderer Name,
                    # gleiche Familien-E-Mail) ist eindeutig ein Zweitaccount, z. B. ein Elternteil.
                    fg0 = mit_account[0]
                    haupt = portal_nach_fg[fg0]
                    fg_nachtrag(a, fg0, True, f"Zweitaccount von {fg0} («{haupt.anzeigename}», gleiche E-Mail): FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»",
                                [f"Portal-Account «{a.anzeigename}» verwendet dieselbe E-Mail wie Fairgate-Kontakt {fg0} («{haupt.anzeigename}»)",
                                 f"«{haupt.anzeigename}» hat bereits einen eigenen Mitglieds-Account — «{a.anzeigename}» ist also ein Zweitaccount (z. B. Elternteil)"])
                    fg_zugeordnet.add(fg0)
                else:
                    # C2 (Vorfrage): der Fairgate-Kontakt hat noch keinen Account — Elternteil oder
                    # dieselbe Person, anders geschrieben? Beides kann der Import umsetzen.
                    fg0 = sorted(per_mail)[0]
                    k = pflichtig[fg0]
                    kname = f"{k.vorname} {k.nachname}"
                    schluessel = f"email:{fg0}"
                    antwort = antwort_zu(ent, schluessel, ("elternteil", "gleiche_person", "unklar"), [fg0])
                    if antwort == "elternteil":
                        fg_nachtrag(a, fg0, True, f"Zweitaccount (Elternteil) von {fg0} («{kname}», gleiche E-Mail, deine Antwort): FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»", [])
                        # kein fg_zugeordnet: für das Kind entsteht ein Neueintritt mit derselben E-Mail
                    elif antwort == "gleiche_person":
                        fg_nachtrag(a, fg0, False, f"Ist Mitglied {fg0} («{kname}», gleiche E-Mail, deine Antwort): FG eintragen, Gruppe «Mitglied», Zielwert setzen", [])
                        mitglied_gefunden(fg0, a)
                        fg_zugeordnet.add(fg0)
                        e.hinweise.append(info(f"{a.anzeigename}: Name im Portal weicht von Fairgate ab («{kname}», {fg0})",
                                               ["Die FG-Nummer ist der Schlüssel — der Name muss nicht angepasst werden",
                                                "Falls gewünscht: im Portal oder in Fairgate angleichen, dann ist es überall gleich"], a))
                    elif antwort == "unklar":
                        klaer(f"{a.anzeigename}: gleiche E-Mail wie Fairgate-Kontakt «{kname}» ({fg0}) — noch offen",
                              [f"Portal-Account «{a.anzeigename}» ({a.email}) · {_einsatz_text(a)} · noch nicht in der Import-Datei",
                               f"Die E-Mail steht in Fairgate bei «{kname}» ({fg0})" + (f", Telefon {k.telefon}" if k.telefon else "")],
                              ["Nachfragen → beim nächsten Abgleich die Vorfrage beantworten; die Import-Zeile entsteht dann automatisch"],
                              helper_id=a.id, fg=fg0)
                        fg_zugeordnet.update(per_mail)
                    else:
                        vorfrage(a, "email", schluessel, [fg0],
                                 f"Gleiche E-Mail wie Fairgate-Kontakt «{kname}» ({fg0}) — und «{kname}» hat noch keinen Portal-Account",
                                 [f"Name im Portal: «{a.anzeigename}» · Name in Fairgate: «{kname}»"],
                                 [("elternteil", f"Elternteil von «{kname}» (Zweitaccount)",
                                   f"Import: FG-Nummer {fg0}, Zielwert 0, Gruppe «Freiwillige» — und ein eigener Account für «{kname}» mit derselben E-Mail"),
                                  ("gleiche_person", "Dieselbe Person, nur anders geschrieben",
                                   f"Import: FG-Nummer {fg0}, Gruppe «Mitglied», Zielwert — der Name bleibt, die FG-Nummer ist der Schlüssel"),
                                  ("unklar", "Weiss nicht — später klären", "Keine Import-Zeile, Klärfall in Schritt 2")])
                        fg_zugeordnet.update(per_mail)
            elif per_name and not (portal_nach_fg.get(sorted(per_name)[0]) and a.typ == Typ.FREIWILLIG
                                   and a.zielwert == 0 and not hat_mitglied):
                # Fall E (Vorfrage): Name bekannt, E-Mail nicht — Neuregistrierung, Zweitaccount unter
                # dem Namen des Kinds oder Namensgleichheit? Ein bereits als Freiwillige(r) mit
                # Zielwert 0 geführter Namensvetter (Mitglied hat eigenen Account) gilt als erledigt.
                fg0 = sorted(per_name)[0]
                k = pflichtig[fg0]
                alt = portal_nach_fg.get(fg0)
                schluessel = f"name:{fg0}"
                kfakt = (f"Fairgate-Kontakt «{k.vorname} {k.nachname}» ({fg0}) mit "
                         + (f"E-Mail {k.email or k.eltern_email}" if (k.email or k.eltern_email) else "keiner E-Mail")
                         + (f" · Telefon {k.telefon}" if k.telefon else ""))
                if alt:
                    antwort = antwort_zu(ent, schluessel, ("zweitaccount", "ersatz", "andere", "unklar"), [fg0])
                    if antwort == "zweitaccount":
                        fg_nachtrag(a, fg0, True, f"Zweitaccount von {fg0} («{alt.anzeigename}», gleicher Name, deine Antwort): FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»", [])
                    elif antwort == "ersatz":
                        fg_nachtrag(a, fg0, False, f"Ersetzt den bisherigen Account von {fg0} ({alt.email}, deine Antwort): FG eintragen, Gruppe «Mitglied», Zielwert setzen", [])
                        ersatz[alt.id] = (alt, a, fg0)
                        mitglied_gefunden(fg0, a)
                    elif antwort == "andere":
                        korrektur(a, "Kein Mitglied in Fairgate — andere Person als das namensgleiche Mitglied "
                                  f"{fg0} (deine Antwort): Freiwillige(r), Zielwert 0",
                                  zielwert="0" if a.zielwert != 0 else "",
                                  gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)))
                    elif antwort == "unklar":
                        klaer(f"{a.anzeigename}: gleicher Name wie Mitglied {fg0}, andere E-Mail — noch offen",
                              [f"Portal-Account «{a.anzeigename}» ({a.email}) · {_einsatz_text(a)} · noch nicht in der Import-Datei", kfakt,
                               f"Bestehender Account zu {fg0}: {alt.email} · {_einsatz_text(alt)}"],
                              ["Nachfragen → beim nächsten Abgleich die Vorfrage beantworten; die Import-Zeile entsteht dann automatisch"],
                              helper_id=a.id, fg=fg0)
                    else:
                        vorfrage(a, "name", schluessel, [fg0],
                                 f"Gleicher Name wie Fairgate-Kontakt {fg0}, aber andere E-Mail — und zu {fg0} gibt es schon den Account {alt.email} ({_einsatz_text(alt)})",
                                 [kfakt, ENTSCHEIDUNGSHILFE],
                                 [("zweitaccount", "Zweitaccount (z. B. Elternteil unter dem Namen des Kinds)",
                                   f"Import: FG-Nummer {fg0}, Zielwert 0, Gruppe «Freiwillige» — beide Accounts bleiben, die Einsätze zählen dem Mitglied"),
                                  ("ersatz", "Dieselbe Person, neuer Account ersetzt den alten",
                                   f"Import: dieser Account wird das Mitglied ({fg0}, Gruppe «Mitglied», Zielwert); der alte Account behält die FG-Nummer, wird Freiwillige(r) mit Zielwert 0 — nichts umhängen, Einsätze beider zählen; löschen später optional"),
                                  ("andere", "Andere Person, nur Namensgleichheit",
                                   "Import: Freiwillige(r), Zielwert 0 — wird dauerhaft gemerkt"),
                                  ("unklar", "Weiss nicht — später klären", "Keine Import-Zeile, Klärfall in Schritt 2")])
                else:
                    antwort = antwort_zu(ent, schluessel, ("gleiche_person", "andere", "unklar"), [fg0])
                    if antwort == "gleiche_person":
                        fg_nachtrag(a, fg0, False, f"Ist Mitglied {fg0} (gleicher Name, andere E-Mail, deine Antwort): FG eintragen, Gruppe «Mitglied», Zielwert setzen", [])
                        mitglied_gefunden(fg0, a)
                        fg_zugeordnet.add(fg0)
                    elif antwort == "andere":
                        if hat_mitglied or a.zielwert != 0 or a.typ == Typ.UNKLASSIFIZIERT:
                            korrektur(a, f"Kein Mitglied in Fairgate — andere Person als «{k.vorname} {k.nachname}» {fg0} (deine Antwort): Freiwillige(r), Zielwert 0",
                                      zielwert="0" if a.zielwert != 0 else "",
                                      gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)))
                        # kein fg_zugeordnet: das Mitglied bekommt einen eigenen Account (Neueintritt)
                    elif antwort == "unklar":
                        klaer(f"{a.anzeigename}: gleicher Name wie Fairgate-Kontakt {fg0}, andere E-Mail — noch offen",
                              [f"Portal-Account «{a.anzeigename}» ({a.email}) · {_einsatz_text(a)} · noch nicht in der Import-Datei", kfakt],
                              ["Nachfragen → beim nächsten Abgleich die Vorfrage beantworten; die Import-Zeile entsteht dann automatisch"],
                              helper_id=a.id, fg=fg0)
                        fg_zugeordnet.update(per_name)
                    else:
                        vorfrage(a, "name", schluessel, [fg0],
                                 f"Gleicher Name wie Fairgate-Kontakt {fg0}, aber andere E-Mail — {fg0} hat noch keinen Portal-Account",
                                 [kfakt],
                                 [("gleiche_person", "Dieselbe Person mit anderer E-Mail",
                                   f"Import: FG-Nummer {fg0}, Gruppe «Mitglied», Zielwert — fertig, keine Portal-Arbeit"),
                                  ("andere", "Andere Person, nur Namensgleichheit",
                                   f"Import: Freiwillige(r), Zielwert 0 (wird dauerhaft gemerkt) — und ein eigener Account für {fg0}"),
                                  ("unklar", "Weiss nicht — später klären", "Keine Import-Zeile, Klärfall in Schritt 2")])
                        fg_zugeordnet.update(per_name)
            elif a.typ == Typ.UNBEKANNT:
                # Fall I: Unbekannte mit Einsätzen → Freiwillige (Vereinsregel, automatisiert)
                if _einsaetze(a):
                    korrektur(a, "Unbekannt mit Einsätzen: wird Freiwillige(r)",
                              zielwert="0" if a.zielwert != 0 else "",
                              gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_UNBEKANNTE, GRUPPE_MITGLIED)))
            elif hat_mitglied or a.zielwert != 0 or a.typ == Typ.UNKLASSIFIZIERT:
                # Fall B: sieht aus wie ein Mitglied, ist aber in Fairgate nirgends zu finden.
                # Gleicher Nachname wie ein Mitglied → erst fragen (Zweitaccount?), dann importieren.
                familie = sorted(nachname_fgs.get(a.nachname.strip().lower(), set()) & fg_mit_mitgliedsaccount)
                schluessel = "nachname:" + ",".join(familie)
                antwort = antwort_zu(ent, schluessel, ("zweitaccount", "andere", "unklar"), familie) if familie else "andere"
                if antwort == "zweitaccount":
                    fg0 = ent["fg"]
                    kind = pflichtig[fg0]
                    fg_nachtrag(a, fg0, True, f"Zweitaccount von {fg0} («{kind.vorname} {kind.nachname}», deine Antwort): FG-Nummer eintragen, Zielwert 0, Gruppe «Freiwillige»", [])
                elif antwort == "andere":
                    korrektur(a, "Kein Mitglied in Fairgate (weder FG, E-Mail noch Name): Freiwillige(r), Zielwert 0"
                              + (" — andere Person als das namensgleiche Mitglied (deine Antwort)" if familie else ""),
                              zielwert="0" if a.zielwert != 0 else "",
                              gruppe=_zielgruppen(a, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED, GRUPPE_UNBEKANNTE)))
                elif antwort == "unklar":
                    mitglieder = [f"«{pflichtig[f].vorname} {pflichtig[f].nachname}» ({f})"
                                  + (f", Telefon {pflichtig[f].telefon}" if pflichtig[f].telefon else "") for f in familie]
                    klaer(f"{a.anzeigename}: Zweitaccount eines Mitglieds {', '.join(familie)}? Noch offen",
                          [f"Portal-Account «{a.anzeigename}» ({a.email}) · {_einsatz_text(a)} · noch nicht in der Import-Datei",
                           f"Gleicher Nachname in Fairgate: {'; '.join(mitglieder)}"],
                          ["Nachfragen (Telefon oben oder E-Mail an den Account) → beim nächsten Abgleich die Vorfrage beantworten; "
                           "die Import-Zeile entsteht dann automatisch"],
                          helper_id=a.id, fg=familie[0])
                else:
                    vorfrage(a, "nachname", schluessel, familie,
                             "Keine FG-Nummer, nirgends in Fairgate — aber " + ("ein Mitglied hat" if len(familie) == 1 else f"{len(familie)} Mitglieder haben") + " denselben Nachnamen",
                             [],
                             [("zweitaccount", "Zweitaccount (Elternteil) von", "Import: FG-Nummer des Kinds, Zielwert 0, Gruppe «Freiwillige» — die Einsätze zählen dem Kind", True),
                              ("andere", "Andere Person, nur Namensgleichheit", "Import: Freiwillige(r), Zielwert 0 — wird dauerhaft gemerkt"),
                              ("unklar", "Weiss nicht — später klären", "Keine Import-Zeile, Klärfall in Schritt 2")])
            # sonst: echte(r) Freiwillige(r) — nichts zu tun

    # ---- Ersatz-Accounts: der alte Account wird Zweitaccount (FG bleibt, Einsätze zählen weiter) --
    for alt, neu, fg0 in ersatz.values():
        e.korrekturen = [z for z in e.korrekturen
                         if not (z.vorname == alt.vorname and z.nachname == alt.nachname and z.email == alt.email)]
        korrektur(alt, f"Bisheriger Account von {fg0}, ersetzt durch {neu.email} (deine Antwort): Zielwert 0, "
                       "Gruppe «Freiwillige» — FG-Nummer bleibt, seine Einsätze zählen weiter dem Mitglied",
                  zielwert="0" if alt.zielwert != 0 else "",
                  gruppe=_zielgruppen(alt, hinzu=(GRUPPE_FREIWILLIGE,), weg=(GRUPPE_MITGLIED,)))
        offen = alt.num_confirmed + alt.num_reserved + alt.num_unconfirmed
        e.hinweise.append(info(f"{alt.anzeigename} ({alt.email}): bisheriger Account, ersetzt durch {neu.email}",
                               ["Nichts muss umgehängt werden — beide Accounts tragen die FG-Nummer, das Cockpit zählt sie zusammen",
                                (f"Noch {offen} offene Einsätze auf dem alten Account" if offen else "Keine offenen Einsätze")
                                + " — löschen ist optional (Portal: «Helfer:in löschen», unwiderruflich, vergangene Einsätze verschwinden aus der Portal-Statistik)"],
                               alt))

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

    # Vorfragen mit Einsätzen zuerst — dort steht am meisten auf dem Spiel
    e.vorfragen.sort(key=lambda v: (-v["einsaetze"], v["name"]))

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
