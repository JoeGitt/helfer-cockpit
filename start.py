#!/usr/bin/env python3
"""Helfer-Cockpit 2 — Start: API-Key (Schlüsselbund), Server, Browser.

  python3 start.py              normaler Start
  python3 start.py --demo       mit anonymisierten Beispieldaten, ohne API-Key
  python3 start.py --key-reset  API-Key neu erfassen
"""
import getpass
import json
import sys
import threading
import webbrowser
from pathlib import Path

from cockpit.api_client import ApiClient
from cockpit.webapp import Zustand, starte_server

ORG_SLUG = "pfadi-winterthur-handball"
KEYRING_SERVICE = "helfereinsatz-api"
KONFIG = Path.home() / ".helfer-cockpit"


def hole_key(reset=False):
    try:
        import keyring
    except ImportError:
        sys.exit("Fehlt: das Paket «keyring». Bitte einmalig:  pip install openpyxl keyring")
    key = None
    if not reset:
        try:
            key = keyring.get_password(KEYRING_SERVICE, ORG_SLUG)
        except Exception as e:
            sys.exit("Schlüsselbund des Betriebssystems nicht erreichbar (%s). "
                     "Zugriff im System prüfen oder mit --key-reset neu erfassen." % e)
    if not key:
        print("Der API-Key wird sicher im Schlüsselbund des Betriebssystems abgelegt.")
        key = getpass.getpass("HELFEREINSATZ API-Key eingeben (Eingabe bleibt unsichtbar): ").strip()
        if not key:
            sys.exit("Kein Key eingegeben, abgebrochen.")
        try:
            keyring.set_password(KEYRING_SERVICE, ORG_SLUG, key)
        except Exception as e:
            sys.exit("Key konnte nicht im Schlüsselbund gespeichert werden (%s)." % e)
        print("Key gespeichert.\n")
    return key


def main():
    demo = "--demo" in sys.argv
    zustand = Zustand(regeln_pfad=KONFIG / "regeln.json",
                      protokoll_pfad=KONFIG / "protokoll.jsonl",
                      ausgabe_dir=Path.cwd() / "Ausgabe")
    if demo:
        fixtures = Path(__file__).parent / "tests" / "fixtures"
        zustand.helpers = json.loads((fixtures / "helpers.json").read_text(encoding="utf-8"))
        zustand.assignments = json.loads((fixtures / "assignments.json").read_text(encoding="utf-8"))
        zustand.stand = "Demo-Daten (fiktiv)"
    else:
        key = hole_key(reset="--key-reset" in sys.argv)
        zustand.api_client_factory = lambda: ApiClient(key, ORG_SLUG)
    server = starte_server(zustand, port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Helfer-Cockpit läuft: {url}")
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
