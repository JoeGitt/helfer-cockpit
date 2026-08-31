import json
import threading
import urllib.request
from pathlib import Path
import pytest
from cockpit.webapp import Zustand, baue_dashboard, starte_server

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

def test_bindet_nur_lokal(tmp_path):
    srv = starte_server(_zustand(tmp_path), port=0)
    assert srv.server_address[0] == "127.0.0.1"
    srv.server_close()


class _LeererClient:
    """Stub: liefert 0 Helfende (Spez. 6.4: unplausibel, Abbruch)."""
    def helpers(self):
        return []


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
