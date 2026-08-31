import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import openpyxl
import pytest
from cockpit.webapp import Zustand, baue_dashboard, starte_server

FG_KOPF = ["Kontakte", "Kontakt-ID Verein", "Primäre E-Mail", "Vorname", "Nachname",
          "Handy", "Mitgliedschaft", "E-Mail Eltern 1", "E-Mail Eltern 2", "Geburtsdatum"]


def _fairgate_bytes(zeilen):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(FG_KOPF)
    for z in zeilen:
        ws.append(z)
    puffer = io.BytesIO()
    wb.save(puffer)
    return puffer.getvalue()

FIXTURES = Path(__file__).parent / "fixtures"

def _zustand(tmp_path):
    return Zustand(
        helpers=json.loads((FIXTURES / "helpers.json").read_text(encoding="utf-8")),
        assignments=json.loads((FIXTURES / "assignments.json").read_text(encoding="utf-8")),
        stand="2026-08-31 14:32",
        regeln_pfad=tmp_path / "regeln.json",
        protokoll_pfad=tmp_path / "protokoll.jsonl",
        ausgabe_dir=tmp_path / "Ausgabe",
        api_client_factory=None,
        fehler="")

def test_dashboard_json(tmp_path):
    d = baue_dashboard(_zustand(tmp_path))
    assert d["kennzahlen"]["mitglieder"] == 3
    fg2417 = next(m for m in d["mitglieder"] if m["fg"] == "FG-2417")
    assert fg2417["ist"] == 2.0 and fg2417["status_saison"] == "erfuellt"
    assert len(fg2417["accounts"]) == 3
    assert d["wer_leistet"]["zweitaccount"] == 2      # num_ok von 101
    assert any(h["code"] == "D6" for h in d["hinweise"])
    assert d["kennzahlen"]["nok_summe"] == 1           # Bericht-Kachel NOK (Spez. 6.2)

def test_dashboard_ohne_abruf(tmp_path):
    z = _zustand(tmp_path)
    z.helpers = None
    d = baue_dashboard(z)
    assert d["stand"] == "" or d["mitglieder"] == []

@pytest.fixture
def server(tmp_path):
    srv = starte_server(_zustand(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()

def test_api_stand_http(server):
    with urllib.request.urlopen(server + "/api/stand") as r:
        d = json.loads(r.read())
    assert d["kennzahlen"]["mitglieder"] == 3

def test_index_wird_ausgeliefert(server):
    with urllib.request.urlopen(server + "/") as r:
        html = r.read().decode("utf-8")
    assert "HELFER-COCKPIT" in html and "app.js" in html

def test_bindet_nur_lokal(tmp_path):
    srv = starte_server(_zustand(tmp_path), port=0)
    assert srv.server_address[0] == "127.0.0.1"
    srv.server_close()


class _LeererClient:
    """Stub: liefert 0 Helfende (Spez. 6.4: unplausibel, Abbruch)."""
    def helpers(self):
        return []


def test_gesamtexport_http(server):
    req = urllib.request.Request(server + "/api/export/gesamt", method="POST", data=b"")
    with urllib.request.urlopen(req) as r:
        d = json.loads(r.read())
    assert d["anzahl"] == 3
    assert Path(d["datei"]).is_file()
    assert Path(d["datei"]).name.startswith("gesamtexport-")


def test_fairgate_upload_liefert_unbekannte_kategorien_feld(server):
    daten = _fairgate_bytes([
        ["x", 9999, "neu@example.ch", "Fremd", "Kategorie", None,
         "Vereinsfremd", None, None, "2000-01-01"],
    ])
    req = urllib.request.Request(server + "/api/fairgate", method="POST", data=daten)
    with urllib.request.urlopen(req) as r:
        d = json.loads(r.read())
    assert d["unbekannte_kategorien"] and "Vereinsfremd" in d["unbekannte_kategorien"][0]
    assert d["neueintritte"] == 0


def test_fairgate_garbage_bytes_liefert_400(server):
    req = urllib.request.Request(server + "/api/fairgate", method="POST",
                                 data=b"nicht mal ansatzweise eine Excel-Datei \x00\x01")
    try:
        urllib.request.urlopen(req)
        assert False, "erwartete HTTPError 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400
        d = json.loads(e.read())
        assert d["fehler"]


class _EventsWirftClient:
    """Stub: helpers() liefert normal, events() scheitert (D6 degradiert, I3)."""
    def __init__(self, helpers):
        self._helpers = helpers

    def helpers(self):
        return self._helpers

    def events(self):
        raise RuntimeError("API für Einsätze nicht erreichbar")


def test_d6_hinweis_bei_assignments_fehler(tmp_path):
    z = _zustand(tmp_path)
    z.api_client_factory = lambda: _EventsWirftClient(z.helpers)
    srv = starte_server(z, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        basis = f"http://127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(basis + "/api/abruf", method="POST", data=b"")
        with urllib.request.urlopen(req) as r:
            d = json.loads(r.read())
        assert not d["fehler"]      # helpers() gelang, nur assignments fehlten
        d6 = [h for h in d["hinweise"] if h["code"] == "D6" and "nicht möglich" in h["text"]]
        assert len(d6) == 1
    finally:
        srv.shutdown()


class _OkClient:
    def __init__(self, helpers, events=None):
        self._helpers, self._events = helpers, (events or [])

    def helpers(self):
        return self._helpers

    def events(self):
        return self._events

    def alle_assignments(self, events):
        return []


def test_d6_degradations_hinweis_verschwindet_nach_erfolgreichem_abruf(tmp_path):
    z = _zustand(tmp_path)
    z.assignments_fehler = True     # simuliert einen vorherigen fehlgeschlagenen Abruf
    z.api_client_factory = lambda: _OkClient(z.helpers)
    srv = starte_server(z, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        basis = f"http://127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(basis + "/api/abruf", method="POST", data=b"")
        with urllib.request.urlopen(req) as r:
            d = json.loads(r.read())
        assert not any(h["code"] == "D6" and "nicht möglich" in h["text"] for h in d["hinweise"])
    finally:
        srv.shutdown()


def test_korruptes_regeln_json_liefert_standardregeln_und_hinweis(tmp_path):
    z = _zustand(tmp_path)
    z.regeln_pfad.parent.mkdir(parents=True, exist_ok=True)
    z.regeln_pfad.write_text("{das ist kein json", encoding="utf-8")
    srv = starte_server(z, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        basis = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(basis + "/api/stand") as r:
            d = json.loads(r.read())
        assert d["kennzahlen"]["mitglieder"] == 3   # trotzdem geladen
        assert any("Regeln" in h["text"] or "beschädigt" in h["text"] for h in d["hinweise"])
        with urllib.request.urlopen(basis + "/api/regeln") as r:
            regeln = json.loads(r.read())
        assert regeln["altersgrenze"] == 16          # Standardregeln
    finally:
        srv.shutdown()


def test_kaputte_route_liefert_500_json_statt_abgerissener_verbindung(server):
    req = urllib.request.Request(server + "/api/regeln", method="POST",
                                 data=b"das ist kein json", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        assert False, "erwartete HTTPError 500"
    except urllib.error.HTTPError as e:
        assert e.code == 500
        d = json.loads(e.read())
        assert d["fehler"]


def test_fremder_host_header_wird_abgewiesen(server):
    req = urllib.request.Request(server + "/api/stand", headers={"Host": "evil.example.com"})
    try:
        urllib.request.urlopen(req)
        assert False, "erwartete HTTPError 403"
    except urllib.error.HTTPError as e:
        assert e.code == 403


def test_normaler_request_kommt_trotz_host_guard_durch(server):
    with urllib.request.urlopen(server + "/api/stand") as r:
        assert r.status == 200


def test_ungueltige_sicht_liefert_400_statt_keyerror(server):
    req = urllib.request.Request(server + "/api/export/saeumige?sicht=galaxie", method="POST", data=b"")
    try:
        urllib.request.urlopen(req)
        assert False, "erwartete HTTPError 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400
        d = json.loads(e.read())
        assert d["fehler"]


def test_api_abruf_log_zaehlt_hinweise(tmp_path):
    z = _zustand(tmp_path)
    z.api_client_factory = lambda: _OkClient(z.helpers)
    srv = starte_server(z, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        basis = f"http://127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(basis + "/api/abruf", method="POST", data=b"")
        with urllib.request.urlopen(req) as r:
            d = json.loads(r.read())
        with urllib.request.urlopen(basis + "/api/protokoll") as r:
            protokoll_liste = json.loads(r.read())
        eintrag = next(e for e in protokoll_liste if e["aktion"] == "api-abruf")
        assert eintrag["hinweise"] == d["kennzahlen"]["hinweise"]
    finally:
        srv.shutdown()


def test_abruf_fehler_lasst_alte_anzeige_stehen(tmp_path):
    z = _zustand(tmp_path)
    z.api_client_factory = lambda: _LeererClient()
    srv = starte_server(z, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        basis = f"http://127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(basis + "/api/abruf", method="POST", data=b"")
        with urllib.request.urlopen(req) as r:
            d = json.loads(r.read())
        assert d["fehler"]
        assert d["kennzahlen"]["mitglieder"] == 3
    finally:
        srv.shutdown()
