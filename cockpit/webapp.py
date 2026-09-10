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
                      schreibe_gesamtexport_xlsx, schreibe_kontaktabweichungen_csv)
from .settings import lade_regeln, lade_regeln_mit_fehler, speichere_regeln, Regeln, KategorieRegel
from . import protokoll

STATIC = Path(__file__).parent / "static"
STATIC_RESOLVED = STATIC.resolve()
SICHTEN = ("saison", "halbjahr")


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


def portal_url(z, helper_id):
    """Detailseite eines Helfers im Portal (Muster verifiziert am echten Portal)."""
    return f"https://app.helfereinsatz.ch/{z.org_slug}/de/helpers/detail/{helper_id}"


def _account_json(z, a):
    return {"id": a.id, "name": a.anzeigename, "typ": a.typ.value, "gruppen": a.gruppen,
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
        "klaerliste": ergebnis.klaerliste,
        "duplikat_warnungen": ergebnis.duplikat_warnungen,
        "unbekannte_kategorien": ergebnis.unbekannte_kategorien,
        "kontakt_abweichungen": [{**a, "portal_url": portal_url(z, a["helper_id"]) if a.get("helper_id") else None}
                                 for a in ergebnis.kontakt_abweichungen],
        "kategorien": ergebnis.kategorien,
        "hinweise": ergebnis.hinweise,
        "import_vorschau": _import_vorschau(ergebnis),
    }


def _import_vorschau(ergebnis):
    """Was in der Import-Datei steht — damit niemand Excel öffnen muss, um es zu wissen."""
    def felder(z):
        teile = []
        if z.gruppe: teile.append(f"Gruppen → {z.gruppe}")
        if z.zielwert: teile.append(f"Zielwert {z.zielwert}")
        if z.telefon: teile.append(f"Telefon {z.telefon}")
        if z.bemerkungen: teile.append(f"Bemerkung {z.bemerkungen}")
        if z.email and z in ergebnis.neueintritte: teile.append(f"E-Mail {z.email}")
        return ", ".join(teile)
    return ([{"name": f"{z.vorname} {z.nachname}".strip(), "art": "Neueintritt",
              "grund": z.grund, "aenderungen": felder(z)} for z in ergebnis.neueintritte]
            + [{"name": f"{z.vorname} {z.nachname}".strip(), "art": "Korrektur",
                "grund": z.grund, "aenderungen": felder(z)} for z in ergebnis.korrekturen])


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
        m_json.append({
            "fg": m.fg, "name": a0.anzeigename, "gruppen": a0.gruppen,
            "soll": m.soll, "ist": m.ist, "soll_konflikt": m.soll_konflikt,
            "status_saison": status(m, "saison", regeln.halbjahresziel),
            "status_halbjahr": status(m, "halbjahr", regeln.halbjahresziel),
            "accounts": [{"id": a.id, "name": a.anzeigename, "typ": a.typ.value,
                          "soll": a.zielwert, "ist": a.ist_wert, "bemerkung": a.bemerkung,
                          "num_ok": a.num_ok, "num_nok": a.num_nok,
                          "num_confirmed": a.num_confirmed, "portal_url": portal_url(z, a.id)}
                         for a in m.accounts]})
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
        "ohne_einsatz": sum(1 for m in m_json if m["ist"] == 0),
        "ist_summe": sum(m["ist"] for m in m_json),
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
                    regeln = lade_regeln(zustand.regeln_pfad)
                    accounts = [classify(h) for h in (zustand.helpers or [])]
                    ergebnis = gleiche_ab(kontakte, accounts, regeln)
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
                    dateien = [import_pfad.name, liste_pfad.name, kontakte_pfad.name]
                    protokoll.logge(zustand.protokoll_pfad, "abgleich", {
                        "geprueft": ergebnis.geprueft,
                        "neueintritte": len(ergebnis.neueintritte),
                        "korrekturen": len(ergebnis.korrekturen),
                        "handarbeit": len(ergebnis.handarbeit),
                        "abweichungen": len(ergebnis.kontakt_abweichungen),
                        "dateien": dateien})
                    antwort = _abgleich_json(zustand, ergebnis)
                    antwort["dateien"] = {"import": str(import_pfad), "liste": str(liste_pfad),
                                          "kontakte": str(kontakte_pfad)}
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
                    return self._json(antwort)
                except (FalscheDatei, ValueError) as e:
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
                    ergebnis = gleiche_ab(zustand.fairgate_kontakte, accounts, regeln)
                except ValueError as e:
                    return self._json({"fehler": str(e)}, 400)
                offen = {"neueintritte": len(ergebnis.neueintritte),
                         "korrekturen": len(ergebnis.korrekturen),
                         "handarbeit": len(ergebnis.handarbeit),
                         "klaerliste": len(ergebnis.klaerliste)}
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
