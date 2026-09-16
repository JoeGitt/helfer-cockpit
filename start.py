#!/usr/bin/env python3
"""Helfer-Cockpit 2 — Start: Datenordner, API-Key (Schlüsselbund), Server, Browser.

  python3 start.py              normaler Start (Einrichtung beim ersten Mal im Browser)
  python3 start.py --demo       mit fiktiven Beispieldaten, ohne API-Key
  python3 start.py --pseudo     mit pseudonymisiertem Vereinsbestand (tests/fixtures/pseudo), ohne API-Key
  python3 start.py --key-reset  gespeicherten API-Key verwerfen (wird im Browser neu abgefragt)
  python3 start.py --port 8473  festen Port verwenden (Standard: 8473, bei Belegung der nächste freie)
"""
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

from cockpit.api_client import ApiClient            # noqa: E402
from cockpit.webapp import Zustand, starte_server   # noqa: E402
from cockpit import standort                        # noqa: E402
from cockpit.version import VERSION                 # noqa: E402

ORG_SLUG = "pfadi-winterthur-handball"
KEYRING_SERVICE = "helfereinsatz-api"
KONFIG = standort.KONFIG
STANDARD_PORT = 8473


def _log_umleiten():
    """Ohne Konsole (pythonw.exe) landen Meldungen in einer Logdatei statt im Nichts."""
    if sys.stdout is None or sys.stderr is None:
        KONFIG.mkdir(parents=True, exist_ok=True)
        f = open(KONFIG / "cockpit.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        sys.exit("Fehlt: das Paket «keyring». Bitte einmalig:  pip install openpyxl keyring")


def key_lesen():
    try:
        return _keyring().get_password(KEYRING_SERVICE, ORG_SLUG)
    except Exception as e:
        print(f"Schlüsselbund nicht erreichbar ({e}) — der Key wird im Browser abgefragt.")
        return None


def key_speichern(key):
    _keyring().set_password(KEYRING_SERVICE, ORG_SLUG, key)


def key_loeschen():
    try:
        _keyring().delete_password(KEYRING_SERVICE, ORG_SLUG)
    except Exception:
        pass


def _port_aus_argv():
    if "--port" in sys.argv:
        try:
            return int(sys.argv[sys.argv.index("--port") + 1])
        except (IndexError, ValueError):
            pass
    return STANDARD_PORT


def _server_starten(zustand, wunsch):
    for port in [wunsch] + [wunsch + i for i in range(1, 20)] + [0]:
        try:
            return starte_server(zustand, port=port)
        except OSError:
            continue
    raise SystemExit("Kein freier Port gefunden.")


def main():
    _log_umleiten()
    demo = "--demo" in sys.argv or "--pseudo" in sys.argv
    zustand = Zustand(org_slug=ORG_SLUG, konfig_dir=KONFIG, demo=demo)
    daten_ordner = standort.lade_standort()
    if daten_ordner:
        zustand.setze_daten_ordner(daten_ordner)
    else:
        # noch nicht eingerichtet: vorläufig wie bisher (~/.helfer-cockpit, Ausgabe neben dem Programm),
        # die Oberfläche fragt beim Start nach dem Datenordner
        zustand.regeln_pfad = KONFIG / "regeln.json"
        zustand.protokoll_pfad = KONFIG / "protokoll.jsonl"
        zustand.ausgabe_dir = Path.cwd() / "Ausgabe"
    if demo:
        fixtures = HIER / "tests" / "fixtures" / ("pseudo" if "--pseudo" in sys.argv else "")
        zustand.helpers = json.loads((fixtures / "helpers.json").read_text(encoding="utf-8"))
        zustand.assignments = json.loads((fixtures / "assignments.json").read_text(encoding="utf-8"))
        zustand.stand = "Demo-Daten (fiktiv)"
    else:
        if "--key-reset" in sys.argv:
            key_loeschen()
        key = key_lesen()
        if key:
            zustand.api_client_factory = lambda: ApiClient(key, ORG_SLUG)

        def setzen(neu):
            key_speichern(neu)
            zustand.api_client_factory = lambda: ApiClient(neu, ORG_SLUG)
        zustand.key_setzen = setzen
        zustand.key_loeschen = key_loeschen
    server = _server_starten(zustand, _port_aus_argv())
    def beenden():
        # Server sauber stoppen; falls etwas hängt, den Prozess nach kurzer Frist hart beenden,
        # damit das Update-Skript den Programmordner tauschen kann
        threading.Thread(target=server.shutdown, daemon=True).start()
        threading.Timer(4.0, lambda: os._exit(0)).start()
    zustand.beenden = beenden
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Helfer-Cockpit {VERSION} läuft: {url}")
    print("Dieses Fenster offen lassen. Schliessen beendet das Cockpit.")
    threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
