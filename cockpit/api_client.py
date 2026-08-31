"""Read-only-Client für die Helfereinsatz-API (Paginierung, Fehlerarten)."""
import json
import urllib.request
import urllib.error

TIMEOUT = 30


class ApiFehler(Exception):
    def __init__(self, art, meldung):
        super().__init__(meldung)
        self.art = art  # "auth" | "netz" | "format"


class ApiClient:
    def __init__(self, key, org_slug="pfadi-winterthur-handball", hole=None):
        self.basis = f"https://api.helfereinsatz.ch/v1/{org_slug}/"
        self._hole = hole or self._hole_urllib(key)

    def _hole_urllib(self, key):
        def hole(pfad):
            req = urllib.request.Request(self.basis + pfad, headers={
                "X-API-KEY": key, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise ApiFehler("auth",
                        "Die API hat den Key abgelehnt (HTTP %d). Key im Portal prüfen "
                        "und mit --key-reset neu erfassen." % e.code)
                raise ApiFehler("netz", "API-Fehler HTTP %d bei %s" % (e.code, pfad))
            except urllib.error.URLError as e:
                raise ApiFehler("netz", "Keine Verbindung zur API (%s). Internet prüfen." % e.reason)
        return hole

    def _alle_seiten(self, pfad_ohne_seite):
        eintraege, seite = [], 1
        while True:
            daten = self._hole(f"{pfad_ohne_seite}/{seite}")
            if not isinstance(daten, dict) or "entries" not in daten:
                raise ApiFehler("format",
                    "Unerwartete API-Antwort bei %s — hat sich die API geändert?" % pfad_ohne_seite)
            eintraege.extend(daten.get("entries") or [])
            if seite >= int(daten.get("pagesNum") or 1):
                return eintraege
            seite += 1

    def helpers(self):
        return self._alle_seiten("helpers")

    def events(self):
        return self._alle_seiten("events")

    def assignments(self, event_id):
        return self._alle_seiten(f"helperassignments/{event_id}")

    def alle_assignments(self, events):
        alle = []
        for ev in events:
            alle.extend(self.assignments(ev["id"]))
        return alle
