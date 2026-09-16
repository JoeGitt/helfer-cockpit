"""Lokaler HTTP-Server: statisches Frontend + JSON-API. Bindet nur an 127.0.0.1."""
import datetime
import io
import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .model import classify, build_mitglieder, status, Typ
from .checks import run_checks, Hinweis
from .fairgate_reader import lies_fairgate, FalscheDatei
from .abgleich import gleiche_ab
from .exports import (schreibe_import_xlsx, schreibe_saeumigen_csv, handarbeitsliste_html,
                      schreibe_gesamtexport_xlsx, schreibe_kontaktabweichungen_csv,
                      import_zeilen_mit_grund, import_begruendung_html)
from .settings import lade_regeln, lade_regeln_mit_fehler, speichere_regeln, Regeln, KategorieRegel
from . import protokoll

STATIC = Path(__file__).parent / "static"
STATIC_RESOLVED = STATIC.resolve()
SICHTEN = ("saison", "halbjahr")


ANTWORTEN = ("zweitaccount", "familie", "andere", "unklar", "elternteil", "gleiche_person", "ersatz")


@dataclass
class Zustand:
    helpers: list = None
    assignments: list = None
    stand: str = ""
    regeln_pfad: Path = None
    protokoll_pfad: Path = None
    ausgabe_dir: Path = None
    api_client_factory: object = None
    fehler: str = ""
    assignments_fehler: bool = False   # D6 degradiert: letzter Einsätze-Abruf ist gescheitert
    org_slug: str = "pfadi-winterthur-handball"   # Teil der Portal-URL (Helfer-Detailseite)
    fairgate_kategorien: dict = None   # FG → Mitgliedschaft aus dem letzten Fairgate-Export
    fairgate_kontakte: list = None     # Kontakte des letzten Exports (nur im Speicher, für die Kontrolle)
    letzter_abgleich: dict = None      # Zusammenfassung des letzten Laufs dieser Sitzung
    letztes_ergebnis: dict = None      # vollständige Antwort des letzten Abgleichs (für Seiten-Neuladen)
    entscheide: dict = None            # Antworten auf Vorfragen dieser Sitzung {helper_id: {antwort, fg}}

    def entscheide_pfad(self):
        return self.ausgabe_dir / "entscheide.json"

    def lade_entscheide(self):
        """Dauerhaft gespeicherte Antworten («Andere Person») plus die dieser Sitzung."""
        gespeichert = {}
        try:
            if self.entscheide_pfad().exists():
                gespeichert = json.loads(self.entscheide_pfad().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            gespeichert = {}
        if not isinstance(gespeichert, dict):
            gespeichert = {}
        return {**gespeichert, **(self.entscheide or {})}, gespeichert

    def speichere_entscheide(self, neue):
        """neue: {helper_id: {antwort, fg, name} | None}. «andere» wird dauerhaft gespeichert,
        «zweitaccount»/«unklar» nur für die Sitzung (lösen sich selbst bzw. sollen wieder gefragt werden),
        None löscht die Antwort."""
        _, gespeichert = self.lade_entscheide()
        self.entscheide = dict(self.entscheide or {})
        for hid, ent in neue.items():
            hid = str(hid)
            gespeichert.pop(hid, None); self.entscheide.pop(hid, None)
            if not ent:
                continue
            eintrag = {"antwort": ent.get("antwort"), "fg": ent.get("fg") or "", "name": ent.get("name") or "",
                       "fall": ent.get("fall") or "", "schluessel": ent.get("schluessel") or "",
                       "kandidaten": ent.get("kandidaten") or "", "zeit": datetime.date.today().isoformat()}
            if eintrag["antwort"] == "andere":
                gespeichert[hid] = eintrag             # dauerhaft: die Frage kommt nicht wieder
            elif eintrag["antwort"] in ANTWORTEN:
                self.entscheide[hid] = eintrag         # nur diese Sitzung: erledigt sich per Import
        self.ausgabe_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.entscheide_pfad().with_suffix(".tmp")
        tmp.write_text(json.dumps(gespeichert, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.entscheide_pfad())


def portal_url(z, helper_id):
    """Detailseite eines Helfers im Portal (Muster verifiziert am echten Portal)."""
    return f"https://app.helfereinsatz.ch/{z.org_slug}/de/helpers/detail/{helper_id}"


def _account_json(z, a):
    return {"id": a.id, "name": a.anzeigename, "email": a.email, "typ": a.typ.value, "gruppen": a.gruppen,
            "fg": a.fg, "zielwert": a.zielwert, "ist_wert": a.ist_wert,
            "num_ok": a.num_ok, "num_nok": a.num_nok, "num_confirmed": a.num_confirmed,
            "num_reserved": a.num_reserved, "bemerkung": a.bemerkung,
            "portal_url": portal_url(z, a.id)}


def _abgleich_json(z, ergebnis):
    """Gemeinsame JSON-Form für Abgleich und Kontrolle."""
    return {
        "zusammenfassung": ergebnis.zusammenfassung,
        "geprueft": ergebnis.geprueft,
        "neueintritte": len(ergebnis.neueintritte),
        "korrekturen": len(ergebnis.korrekturen),
        "handarbeit": [{**vars(h), "portal_url": portal_url(z, h.helper_id) if h.helper_id else None}
                       for h in ergebnis.handarbeit],
        "klaerliste": [({**k, "portal_url": portal_url(z, k["helper_id"]) if k.get("helper_id") else None}
                        if isinstance(k, dict) else {"titel": str(k), "fakten": [], "optionen": [], "wo": "", "portal_url": None})
                       for k in ergebnis.klaerliste],
        "duplikat_warnungen": ergebnis.duplikat_warnungen,
        "unbekannte_kategorien": ergebnis.unbekannte_kategorien,
        "kontakt_abweichungen": [{**a, "portal_url": portal_url(z, a["helper_id"]) if a.get("helper_id") else None}
                                 for a in ergebnis.kontakt_abweichungen],
        "kategorien": ergebnis.kategorien,
        "hinweise": [({**h, "portal_url": portal_url(z, h["helper_id"]) if h.get("helper_id") else None}
                      if isinstance(h, dict) else {"titel": str(h), "fakten": [], "optionen": [], "portal_url": None})
                     for h in ergebnis.hinweise],
        "vorfragen": [{**v, "portal_url": portal_url(z, v["helper_id"]),
                       "kandidaten": [{**k, "portal_url": portal_url(z, _helper_id_zu_fg(z, k["fg"]))} for k in v["kandidaten"]]}
                      for v in ergebnis.vorfragen],
        "entscheide": _entscheide_json(z),
        "import_vorschau": _import_vorschau(ergebnis),
    }


def _helper_id_zu_fg(z, fg):
    for h in z.helpers or []:
        a = classify(h)
        if a.fg == fg and a.typ == Typ.MITGLIED:
            return a.id
    return None


def _entscheide_json(z):
    """Alle wirksamen Antworten (Sitzung + gespeichert), damit die Oberfläche sie zeigen und ändern kann."""
    alle, gespeichert = z.lade_entscheide()
    return {hid: {**e, "gespeichert": hid in gespeichert} for hid, e in alle.items()}


def abgleich_ausfuehren(zustand, kontakte, protokollieren=True):
    """Abgleich rechnen, Ausgabedateien schreiben, Antwort merken. Gemeinsam für Fairgate-Upload
    und Vorfragen-Antworten (die Import-Datei wird mit den Antworten neu erzeugt)."""
    regeln = lade_regeln(zustand.regeln_pfad)
    accounts = [classify(h) for h in (zustand.helpers or [])]
    entscheide, _ = zustand.lade_entscheide()
    ergebnis = gleiche_ab(kontakte, accounts, regeln, entscheide=entscheide)
    zustand.fairgate_kategorien = {k.fg: k.kategorie for k in kontakte if k.kategorie}
    zustand.fairgate_kontakte = kontakte
    zustand.ausgabe_dir.mkdir(parents=True, exist_ok=True)
    heute = datetime.date.today().isoformat()
    import_pfad = zustand.ausgabe_dir / f"import-{heute}.xlsx"
    schreibe_import_xlsx(ergebnis.neueintritte + ergebnis.korrekturen, import_pfad)
    liste_pfad = zustand.ausgabe_dir / f"handarbeitsliste-{heute}.html"
    liste_pfad.write_text(handarbeitsliste_html(ergebnis), encoding="utf-8")
    kontakte_pfad = zustand.ausgabe_dir / f"kontaktdaten-abweichungen-{heute}.csv"
    schreibe_kontaktabweichungen_csv(ergebnis.kontakt_abweichungen, kontakte_pfad)
    begruendung_pfad = zustand.ausgabe_dir / f"import-{heute}-begruendung.html"
    begruendung_pfad.write_text(import_begruendung_html(ergebnis, import_pfad.name), encoding="utf-8")
    dateien = [import_pfad.name, liste_pfad.name, kontakte_pfad.name, begruendung_pfad.name]
    if protokollieren:
        protokoll.logge(zustand.protokoll_pfad, "abgleich", {
            "geprueft": ergebnis.geprueft,
            "neueintritte": len(ergebnis.neueintritte),
            "korrekturen": len(ergebnis.korrekturen),
            "handarbeit": len(ergebnis.handarbeit),
            "vorfragen": len(ergebnis.vorfragen),
            "abweichungen": len(ergebnis.kontakt_abweichungen),
            "dateien": dateien})
    antwort = _abgleich_json(zustand, ergebnis)
    antwort["dateien"] = {"import": str(import_pfad), "liste": str(liste_pfad),
                          "kontakte": str(kontakte_pfad), "begruendung": str(begruendung_pfad)}
    zustand.letztes_ergebnis = antwort
    zustand.letzter_abgleich = {
        "zeit": datetime.datetime.now().isoformat(timespec="seconds"),
        "zusammenfassung": ergebnis.zusammenfassung,
        "geprueft": ergebnis.geprueft,
        "neueintritte": len(ergebnis.neueintritte),
        "korrekturen": len(ergebnis.korrekturen),
        "handarbeit": len(ergebnis.handarbeit),
        "klaerliste": len(ergebnis.klaerliste),
        "dateien": dateien}
    return antwort


def _import_vorschau(ergebnis):
    """Was in der Import-Datei steht und warum — mit der Excel-Zeilennummer (Kopfzeile = 1),
    damit «Zeile 14» im Cockpit und in Excel dasselbe meint. Reihenfolge wie in der Datei."""
    return import_zeilen_mit_grund(ergebnis)


def baue_dashboard(z):
    if not z.helpers:
        return {"stand": "", "fehler": z.fehler, "kennzahlen": {}, "mitglieder": [],
                "hinweise": [], "wer_leistet": {}, "alle_accounts": [],
                "kategorie_erfuellung": [], "api_verfuegbar": z.api_client_factory is not None,
                "letzter_abgleich": z.letzter_abgleich}
    regeln, regeln_fehler = lade_regeln_mit_fehler(z.regeln_pfad)
    accounts = [classify(h) for h in z.helpers]
    mitglieder = build_mitglieder(accounts)
    hinweise = list(run_checks(accounts, mitglieder, z.assignments))
    if regeln_fehler:
        hinweise.append(Hinweis("REGELN", "warnung", regeln_fehler, []))
    if z.assignments_fehler:
        hinweise.append(Hinweis("D6", "hinweis",
            "Gutschrift-Prüfung nicht möglich — Einsätze konnten nicht abgerufen werden.", []))
    wer = {}
    for a in accounts:
        wer[a.typ.value] = wer.get(a.typ.value, 0) + a.num_ok + a.num_confirmed
    m_json = []
    for m in mitglieder:
        a0 = m.mitglieds_account
        acc_json = lambda a: {"id": a.id, "name": a.anzeigename, "typ": a.typ.value, "email": a.email,
                              "soll": a.zielwert, "ist": a.ist_wert, "bemerkung": a.bemerkung, "fgs": a.fgs or [],
                              "num_ok": a.num_ok, "num_nok": a.num_nok,
                              "num_confirmed": a.num_confirmed, "portal_url": portal_url(z, a.id)}
        fam = m.familie
        m_json.append({
            "fg": m.fg, "name": a0.anzeigename, "gruppen": a0.gruppen,
            "soll": m.soll, "ist": m.ist, "soll_konflikt": m.soll_konflikt,
            "status_saison": status(m, "saison", regeln.halbjahresziel),
            "status_halbjahr": status(m, "halbjahr", regeln.halbjahresziel),
            "accounts": [acc_json(a) for a in m.accounts],
            "familie": ({"name": fam.name, "schluessel": fam.schluessel, "fgs": fam.fgs, "soll": fam.soll, "ist": fam.ist,
                         "accounts": [acc_json(a) for a in fam.accounts]} if fam else None)})
    # Erfüllung nach Fairgate-Kategorie: nur wenn ein Export geladen wurde (Spez 6.2)
    kategorie_erfuellung = []
    if z.fairgate_kategorien:
        agg = {}
        for m in mitglieder:
            kat = z.fairgate_kategorien.get(m.fg)
            if not kat:
                continue
            eintrag = agg.setdefault(kat, {"kategorie": kat, "gesamt": 0, "erreicht": 0})
            eintrag["gesamt"] += 1
            if status(m, "halbjahr", regeln.halbjahresziel) == "erfuellt":
                eintrag["erreicht"] += 1
        kategorie_erfuellung = sorted(agg.values(), key=lambda e: e["kategorie"])
    kennzahlen = {
        "mitglieder": len(mitglieder),
        "erfuellt": sum(1 for m in m_json if m["status_saison"] == "erfuellt"),
        "halbjahr_erreicht": sum(1 for m in m_json if m["status_halbjahr"] == "erfuellt"),
        "ohne_einsatz": sum(1 for m in m_json if (m["familie"]["ist"] if m["familie"] else m["ist"]) == 0),
        "ist_summe": (sum(m["ist"] for m in m_json if not m["familie"])
                      + sum(f.ist for f in {id(m.familie): m.familie for m in mitglieder if m.familie}.values())),
        "familien": len({id(m.familie) for m in mitglieder if m.familie}),
        "soll_summe": sum(m["soll"] for m in m_json),
        "zweitaccounts": sum(1 for a in accounts if a.typ == Typ.ZWEITACCOUNT),
        "hinweise": len(hinweise),
        "nok_summe": sum(a.num_nok for a in accounts),
    }
    return {"stand": z.stand, "fehler": z.fehler, "kennzahlen": kennzahlen,
            "mitglieder": m_json, "wer_leistet": wer,
            "alle_accounts": [_account_json(z, a) for a in accounts],
            "kategorie_erfuellung": kategorie_erfuellung,
            "api_verfuegbar": z.api_client_factory is not None,
            "letzter_abgleich": z.letzter_abgleich,
            "hinweise": [{"code": h.code, "schweregrad": h.schweregrad,
                          "text": h.text, "betroffene": h.betroffene} for h in hinweise]}


def _host_erlaubt(host):
    host = (host or "").strip()
    return (host in ("127.0.0.1", "localhost")
            or host.startswith("127.0.0.1:") or host.startswith("localhost:"))


def starte_server(zustand, port=0):
    class CockpitHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):      # keine Zugriffe auf stdout spammen
            pass

        def _json(self, daten, code=200):
            body = json.dumps(daten, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # DNS-Rebinding-Schutz: nur Requests mit lokalem Host-Header akzeptieren, auch
        # wenn ein Angreifer eine fremde Seite dazu bringt, gegen 127.0.0.1 zu senden.
        def _host_ok(self):
            return _host_erlaubt(self.headers.get("Host"))

        def do_GET(self):
            if not self._host_ok():
                return self._json({"fehler": "Ungültiger Host-Header — Zugriff verweigert."}, 403)
            try:
                return self._do_GET()
            except Exception as e:
                return self._json({"fehler": str(e)}, 500)

        def _do_GET(self):
            pfad = urlparse(self.path).path
            if pfad == "/api/stand":
                return self._json(baue_dashboard(zustand))
            if pfad == "/api/regeln":
                from dataclasses import asdict
                return self._json(asdict(lade_regeln(zustand.regeln_pfad)))
            if pfad == "/api/entscheide":
                _, gespeichert = zustand.lade_entscheide()
                return self._json({"entscheide": gespeichert})
            if pfad == "/api/abgleich/letzter":
                if not zustand.letztes_ergebnis:
                    return self._json({"fehler": "In dieser Sitzung wurde noch kein Abgleich gemacht."}, 404)
                return self._json(zustand.letztes_ergebnis)
            if pfad == "/api/protokoll":
                return self._json(protokoll.lese(zustand.protokoll_pfad))
            # erzeugte Ausgabedateien im Browser öffnen (nur Dateien direkt im Ausgabe-Ordner)
            if pfad.startswith("/ausgabe/") and zustand.ausgabe_dir:
                name = pfad[len("/ausgabe/"):]
                ziel = (zustand.ausgabe_dir / name)
                wurzel = zustand.ausgabe_dir.resolve()
                if ("/" in name or "\\" in name or not name or not ziel.is_file()
                        or ziel.resolve().parent != wurzel):
                    return self._json({"fehler": "Datei nicht gefunden."}, 404)
                typ, disposition = {
                    "html": ("text/html; charset=utf-8", "inline"),
                    "csv": ("text/csv; charset=utf-8", "attachment"),
                    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             "attachment"),
                }.get(ziel.suffix.lstrip("."), ("application/octet-stream", "attachment"))
                body = ziel.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Disposition", f'{disposition}; filename="{ziel.name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # statische Dateien
            datei = STATIC / ("index.html" if pfad == "/" else pfad.lstrip("/").removeprefix("static/"))
            if datei.is_file() and STATIC_RESOLVED in datei.resolve().parents:
                typ = {"html": "text/html", "js": "text/javascript", "css": "text/css",
                       "png": "image/png", "woff2": "font/woff2"}.get(
                           datei.suffix.lstrip("."), "application/octet-stream")
                body = datei.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", f"{typ}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json({"fehler": "nicht gefunden"}, 404)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n)

        def do_POST(self):
            if not self._host_ok():
                return self._json({"fehler": "Ungültiger Host-Header — Zugriff verweigert."}, 403)
            try:
                return self._do_POST()
            except Exception as e:
                return self._json({"fehler": str(e)}, 500)

        def _do_POST(self):
            u = urlparse(self.path)
            if u.path == "/api/abruf":
                try:
                    client = zustand.api_client_factory()
                    neue_helpers = client.helpers()
                    if not neue_helpers:
                        raise RuntimeError("Die API hat 0 Helfende geliefert — unplausibel, "
                                           "Anzeige nicht aktualisiert.")
                    # Erst validieren, dann übernehmen: bei Fehler bleibt der zuletzt
                    # geladene Stand sichtbar (Spez. Kap. 8).
                    zustand.helpers = neue_helpers
                    try:
                        zustand.assignments = client.alle_assignments(client.events())
                        zustand.assignments_fehler = False
                    except Exception:
                        zustand.assignments = None   # D6 degradiert (Spez. 6.4)
                        zustand.assignments_fehler = True
                    zustand.stand = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
                    zustand.fehler = ""
                    dashboard = baue_dashboard(zustand)
                    protokoll.logge(zustand.protokoll_pfad, "api-abruf",
                                    {"accounts": len(zustand.helpers),
                                     "hinweise": dashboard["kennzahlen"]["hinweise"]})
                    return self._json(dashboard)
                except Exception as e:
                    zustand.fehler = str(e)
                return self._json(baue_dashboard(zustand))
            if u.path == "/api/fairgate":
                daten = self._body()
                try:
                    kontakte = lies_fairgate(io.BytesIO(daten))
                    return self._json(abgleich_ausfuehren(zustand, kontakte))
                except (FalscheDatei, ValueError) as e:
                    return self._json({"fehler": str(e)}, 400)
            if u.path == "/api/entscheide/loeschen":
                daten = json.loads(self._body() or b"{}")
                ids = daten.get("helper_ids") or []
                zustand.speichere_entscheide({str(h): None for h in ids})
                if zustand.fairgate_kontakte:
                    abgleich_ausfuehren(zustand, zustand.fairgate_kontakte, protokollieren=False)
                _, gespeichert = zustand.lade_entscheide()
                return self._json({"entscheide": gespeichert, "abgleich_aktualisiert": bool(zustand.fairgate_kontakte)})
            if u.path == "/api/abgleich/entscheide":
                # Vorfragen beantworten: Antworten merken und die Import-Datei damit neu erzeugen
                if not zustand.fairgate_kontakte:
                    return self._json({"fehler": "Zuerst den Fairgate-Export laden — die Vorfragen gehören zu einem Abgleich."}, 400)
                try:
                    daten = json.loads(self._body() or b"{}")
                    neue = daten.get("entscheide") or {}
                    if not isinstance(neue, dict):
                        raise ValueError("entscheide muss ein Objekt sein")
                    for ent in neue.values():
                        if ent and ent.get("antwort") not in ANTWORTEN:
                            raise ValueError("Unbekannte Antwort")
                    if daten.get("zuruecksetzen"):
                        _, gespeichert = zustand.lade_entscheide()
                        neue = {**{hid: None for hid in gespeichert}, **neue}
                    zustand.speichere_entscheide(neue)
                    protokoll.logge(zustand.protokoll_pfad, "entscheide",
                                    {"beantwortet": sum(1 for v in neue.values() if v),
                                     "geloescht": sum(1 for v in neue.values() if not v)})
                    return self._json(abgleich_ausfuehren(zustand, zustand.fairgate_kontakte, protokollieren=False))
                except ValueError as e:
                    return self._json({"fehler": str(e)}, 400)
            if u.path == "/api/abgleich/kontrolle":
                # Schritt 4 des geführten Abgleichs: Portal frisch holen und mit denselben
                # Fairgate-Kontakten nochmals vergleichen — erwartet «Alles synchron».
                if not zustand.fairgate_kontakte:
                    return self._json({"fehler": "Noch kein Fairgate-Export in dieser Sitzung geladen — "
                                       "die Kontrolle braucht denselben Export wie der Abgleich."}, 400)
                if zustand.api_client_factory is not None:
                    try:
                        client = zustand.api_client_factory()
                        neue = client.helpers()
                        if neue:
                            zustand.helpers = neue
                            zustand.stand = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
                    except Exception as e:
                        return self._json({"fehler": f"Portal-Daten konnten nicht frisch geholt werden: {e}"}, 502)
                regeln = lade_regeln(zustand.regeln_pfad)
                accounts = [classify(h) for h in (zustand.helpers or [])]
                try:
                    entscheide, _ = zustand.lade_entscheide()
                    ergebnis = gleiche_ab(zustand.fairgate_kontakte, accounts, regeln, entscheide=entscheide)
                except ValueError as e:
                    return self._json({"fehler": str(e)}, 400)
                offen = {"neueintritte": len(ergebnis.neueintritte),
                         "korrekturen": len(ergebnis.korrekturen),
                         "handarbeit": len(ergebnis.handarbeit),
                         "klaerliste": len(ergebnis.klaerliste),
                         "vorfragen": len(ergebnis.vorfragen)}
                synchron = not any(offen.values())
                protokoll.logge(zustand.protokoll_pfad, "kontrolle", {"synchron": synchron, **offen})
                antwort = _abgleich_json(zustand, ergebnis)
                antwort.update({"synchron": synchron, "offen": offen})
                return self._json(antwort)
            if u.path == "/api/regeln":
                daten = json.loads(self._body())
                email_abweichung = daten.get("email_abweichung") or "info"
                if email_abweichung not in ("info", "handarbeit"):
                    return self._json({"fehler": "email_abweichung muss «info» oder «handarbeit» sein."}, 400)
                regeln = Regeln(kategorien=[KategorieRegel(**k) for k in daten["kategorien"]],
                                altersgrenze=int(daten["altersgrenze"]),
                                halbjahresziel=int(daten["halbjahresziel"]),
                                email_abweichung=email_abweichung)
                speichere_regeln(regeln, zustand.regeln_pfad)
                return self._json({"ok": True})
            if u.path == "/api/export/saeumige":
                sicht = parse_qs(u.query).get("sicht", ["saison"])[0]
                if sicht not in SICHTEN:
                    return self._json({"fehler": f"Ungültige Sicht «{sicht}» — erlaubt: "
                                       + ", ".join(SICHTEN) + "."}, 400)
                regeln = lade_regeln(zustand.regeln_pfad)
                accounts = [classify(h) for h in (zustand.helpers or [])]
                mitglieder = build_mitglieder(accounts)
                zustand.ausgabe_dir.mkdir(parents=True, exist_ok=True)
                pfad = zustand.ausgabe_dir / f"saeumige-{sicht}-{datetime.date.today().isoformat()}.csv"
                n = schreibe_saeumigen_csv(mitglieder, sicht, regeln.halbjahresziel, pfad)
                protokoll.logge(zustand.protokoll_pfad, "saeumigen-csv",
                                {"sicht": sicht, "anzahl": n, "dateien": [pfad.name]})
                return self._json({"anzahl": n, "datei": str(pfad)})
            if u.path == "/api/export/gesamt":
                regeln = lade_regeln(zustand.regeln_pfad)
                accounts = [classify(h) for h in (zustand.helpers or [])]
                mitglieder = build_mitglieder(accounts)
                zustand.ausgabe_dir.mkdir(parents=True, exist_ok=True)
                pfad = zustand.ausgabe_dir / f"gesamtexport-{datetime.date.today().isoformat()}.xlsx"
                n = schreibe_gesamtexport_xlsx(mitglieder, regeln.halbjahresziel, pfad,
                                               accounts=accounts)
                protokoll.logge(zustand.protokoll_pfad, "gesamtexport",
                                {"anzahl": n, "dateien": [pfad.name]})
                return self._json({"anzahl": n, "datei": str(pfad)})
            self._json({"fehler": "nicht gefunden"}, 404)

    return ThreadingHTTPServer(("127.0.0.1", port), CockpitHandler)
