"""Lokaler HTTP-Server: statisches Frontend + JSON-API. Bindet nur an 127.0.0.1."""
import datetime
import json
import tempfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .model import classify, build_mitglieder, status, Typ
from .checks import run_checks
from .fairgate_reader import lies_fairgate, FalscheDatei
from .abgleich import gleiche_ab
from .exports import (schreibe_import_xlsx, schreibe_saeumigen_csv, handarbeitsliste_html,
                      schreibe_gesamtexport_xlsx)
from .settings import lade_regeln, speichere_regeln, Regeln, KategorieRegel
from . import protokoll

STATIC = Path(__file__).parent / "static"


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


def baue_dashboard(z):
    if not z.helpers:
        return {"stand": "", "fehler": z.fehler, "kennzahlen": {}, "mitglieder": [],
                "hinweise": [], "wer_leistet": {}}
    regeln = lade_regeln(z.regeln_pfad)
    accounts = [classify(h) for h in z.helpers]
    mitglieder = build_mitglieder(accounts)
    hinweise = run_checks(accounts, mitglieder, z.assignments)
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
            "accounts": [{"name": a.anzeigename, "typ": a.typ.value,
                          "soll": a.zielwert, "ist": a.ist_wert, "bemerkung": a.bemerkung}
                         for a in m.accounts]})
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
            "hinweise": [{"code": h.code, "schweregrad": h.schweregrad,
                          "text": h.text, "betroffene": h.betroffene} for h in hinweise]}


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

        def do_GET(self):
            pfad = urlparse(self.path).path
            if pfad == "/api/stand":
                return self._json(baue_dashboard(zustand))
            if pfad == "/api/regeln":
                from dataclasses import asdict
                return self._json(asdict(lade_regeln(zustand.regeln_pfad)))
            if pfad == "/api/protokoll":
                return self._json(protokoll.lese(zustand.protokoll_pfad))
            # statische Dateien
            datei = STATIC / ("index.html" if pfad == "/" else pfad.lstrip("/").removeprefix("static/"))
            if datei.is_file() and STATIC in datei.resolve().parents:
                typ = {"html": "text/html", "js": "text/javascript", "css": "text/css",
                       "png": "image/png"}.get(datei.suffix.lstrip("."), "application/octet-stream")
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
                    except Exception:
                        zustand.assignments = None   # D6 degradiert (Spez. 6.4)
                    zustand.stand = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
                    zustand.fehler = ""
                    protokoll.logge(zustand.protokoll_pfad, "api-abruf",
                                    {"accounts": len(zustand.helpers)})
                except Exception as e:
                    zustand.fehler = str(e)
                return self._json(baue_dashboard(zustand))
            if u.path == "/api/fairgate":
                daten = self._body()
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                    f.write(daten)
                    tmp = Path(f.name)
                try:
                    kontakte = lies_fairgate(tmp)
                    regeln = lade_regeln(zustand.regeln_pfad)
                    accounts = [classify(h) for h in (zustand.helpers or [])]
                    ergebnis = gleiche_ab(kontakte, accounts, regeln)
                    zustand.ausgabe_dir.mkdir(parents=True, exist_ok=True)
                    heute = datetime.date.today().isoformat()
                    import_pfad = zustand.ausgabe_dir / f"import-{heute}.xlsx"
                    schreibe_import_xlsx(ergebnis.neueintritte + ergebnis.korrekturen, import_pfad)
                    liste_pfad = zustand.ausgabe_dir / f"handarbeitsliste-{heute}.html"
                    liste_pfad.write_text(handarbeitsliste_html(ergebnis), encoding="utf-8")
                    protokoll.logge(zustand.protokoll_pfad, "abgleich", {
                        "geprueft": ergebnis.geprueft,
                        "neueintritte": len(ergebnis.neueintritte),
                        "korrekturen": len(ergebnis.korrekturen),
                        "handarbeit": len(ergebnis.handarbeit),
                        "dateien": [import_pfad.name, liste_pfad.name]})
                    return self._json({
                        "zusammenfassung": ergebnis.zusammenfassung,
                        "neueintritte": len(ergebnis.neueintritte),
                        "korrekturen": len(ergebnis.korrekturen),
                        "handarbeit": [vars(h) for h in ergebnis.handarbeit],
                        "klaerliste": ergebnis.klaerliste,
                        "duplikat_warnungen": ergebnis.duplikat_warnungen,
                        "dateien": {"import": str(import_pfad), "liste": str(liste_pfad)}})
                except (FalscheDatei, ValueError) as e:
                    return self._json({"fehler": str(e)}, 400)
                finally:
                    tmp.unlink(missing_ok=True)
            if u.path == "/api/regeln":
                daten = json.loads(self._body())
                regeln = Regeln(kategorien=[KategorieRegel(**k) for k in daten["kategorien"]],
                                altersgrenze=int(daten["altersgrenze"]),
                                halbjahresziel=int(daten["halbjahresziel"]))
                speichere_regeln(regeln, zustand.regeln_pfad)
                return self._json({"ok": True})
            if u.path == "/api/export/saeumige":
                sicht = parse_qs(u.query).get("sicht", ["saison"])[0]
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
                n = schreibe_gesamtexport_xlsx(mitglieder, regeln.halbjahresziel, pfad)
                protokoll.logge(zustand.protokoll_pfad, "gesamtexport",
                                {"anzahl": n, "dateien": [pfad.name]})
                return self._json({"anzahl": n, "datei": str(pfad)})
            self._json({"fehler": "nicht gefunden"}, 404)

    return ThreadingHTTPServer(("127.0.0.1", port), CockpitHandler)
