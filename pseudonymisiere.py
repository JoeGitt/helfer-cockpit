#!/usr/bin/env python3
"""Pseudonymisierte Testdaten erzeugen — ohne dass Rohdaten je den Rechner verlassen.

Liest den echten Portal-Bestand über die API (Key aus dem Schlüsselbund) und optional
einen Fairgate-Export, ersetzt alle Personendaten konsistent durch Kunstwerte und schreibt
das Ergebnis nach tests/fixtures/pseudo/. Beziehungen bleiben erhalten (gleicher echter
Name → gleicher Kunstname, gleiche echte E-Mail → gleiche Kunst-E-Mail, gleiche FG-Nummer →
gleiche Kunst-FG-Nummer in Portal UND Fairgate), damit Abgleich, Duplikat-Wächter und
Datenqualitäts-Checks auf den Kunstdaten genauso reagieren wie auf den echten.

  python3 pseudonymisiere.py                          nur Portal (API)
  python3 pseudonymisiere.py --fairgate export.xlsx   Portal + Fairgate-Export
  python3 pseudonymisiere.py --nur-fairgate export.xlsx

Ausgabe: helpers.json, events.json, assignments.json, fairgate.xlsx, bericht.txt (nur Zähler).
Das Script gibt nie Personendaten auf dem Bildschirm aus.
"""
import argparse
import datetime
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ZIEL = Path(__file__).parent / "tests" / "fixtures" / "pseudo"
SALZ_DATEI = ZIEL / ".salz"          # sorgt für reproduzierbare Zuordnung über mehrere Läufe

VORNAMEN = ["Lena", "Noah", "Mia", "Luca", "Emma", "Leon", "Sara", "Elias", "Nina", "Jonas",
            "Lara", "Finn", "Elin", "Tim", "Anna", "Ben", "Livia", "Nils", "Zoe", "Jan", "Lia",
            "Levin", "Alina", "Samuel", "Nora", "David", "Elena", "Julian", "Sina", "Fabio",
            "Petra", "Reto", "Ueli", "Beat", "Ruth", "Marco", "Rita", "Andrea", "Daniel", "Sandra",
            "Thomas", "Monika", "Peter", "Claudia", "Stefan", "Karin", "Urs", "Brigitte", "Roger",
            "Susanne", "Martin", "Barbara", "Christian", "Nicole", "Michael", "Esther", "Patrick"]
NACHNAMEN = ["Brunner", "Keller", "Meili", "Vogt", "Ackermann", "Steiner", "Gerber", "Weber",
             "Odermatt", "Frei", "Steiger", "Huber", "Meier", "Müller", "Schmid", "Baumann",
             "Fischer", "Graf", "Zimmermann", "Wyss", "Bühler", "Roth", "Kunz", "Lüthi", "Suter",
             "Moser", "Hofer", "Widmer", "Bachmann", "Berger", "Kaufmann", "Rüegg", "Bosshard",
             "Hess", "Wenger", "Egli", "Marti", "Ott", "Frey", "Stalder", "Brändli", "Kohler",
             "Schneider", "Tanner", "Zbinden", "Ammann", "Bieri", "Furrer", "Gasser", "Haas"]


class Pseudo:
    """Deterministische, konsistente Ersetzungen (Salz + SHA-256)."""

    def __init__(self, salz):
        self.salz = salz
        self.vornamen, self.nachnamen, self.mails, self.telefone, self.fg = {}, {}, {}, {}, {}
        self.helper_ids = {}
        self.zaehler = {"vornamen": 0, "nachnamen": 0, "mails": 0, "telefone": 0, "fg": 0, "helper_ids": 0}

    def _h(self, art, wert):
        return int(hashlib.sha256(f"{self.salz}|{art}|{wert}".encode("utf-8")).hexdigest(), 16)

    def _casing(self, original, fake):
        if not original:
            return fake
        if original == original.lower():
            return fake.lower()
        if original == original.upper():
            return fake.upper()
        return fake

    def _name(self, tabelle, liste, art, wert):
        if not wert:
            return ""
        schluessel = wert.strip().lower()
        if schluessel not in tabelle:
            n = len(tabelle)
            basis = liste[self._h(art, schluessel) % len(liste)]
            tabelle[schluessel] = basis if n < len(liste) else f"{basis}{n // len(liste) + 1}"
            self.zaehler[art] += 1
        return self._casing(wert.strip(), tabelle[schluessel])

    def vorname(self, w):
        return self._name(self.vornamen, VORNAMEN, "vornamen", w)

    def nachname(self, w):
        return self._name(self.nachnamen, NACHNAMEN, "nachnamen", w)

    def mail(self, w):
        if not w:
            return ""
        schluessel = w.strip().lower()
        if schluessel not in self.mails:
            self.mails[schluessel] = f"person{len(self.mails) + 1:04d}@example.ch"
            self.zaehler["mails"] += 1
        fake = self.mails[schluessel]
        return fake if w.strip() == schluessel else fake[0].upper() + fake[1:]   # Case-Struktur erhalten

    def telefon(self, w):
        if not w:
            return ""
        if w not in self.telefone:
            rnd = random.Random(self._h("telefon", w))
            self.telefone[w] = "+4179" + "".join(str(rnd.randint(0, 9)) for _ in range(7))
            self.zaehler["telefone"] += 1
        return self.telefone[w]

    def fg_nummer(self, nummer):
        nummer = str(nummer).strip().split(".")[0]
        if nummer not in self.fg:
            self.fg[nummer] = str(7000 + len(self.fg) + 1)
            self.zaehler["fg"] += 1
        return self.fg[nummer]

    def helper_id(self, hid):
        if hid not in self.helper_ids:
            self.helper_ids[hid] = 1000 + len(self.helper_ids) + 1
            self.zaehler["helper_ids"] += 1
        return self.helper_ids[hid]

    def geburtsdatum(self, w):
        """Jahr und Monat bleiben (Altersregel!), der Tag wird ersetzt."""
        if not w:
            return w
        try:
            d = datetime.date.fromisoformat(str(w)[:10])
        except ValueError:
            return ""
        rnd = random.Random(self._h("geb", str(w)))
        return d.replace(day=rnd.randint(1, 28)).isoformat()

    def bemerkung(self, text):
        """FG-Nummern konsistent ersetzen, Struktur (Standard / nicht am Anfang) erhalten,
        allen übrigen Freitext verwerfen."""
        if not text:
            return ""
        m = re.search(r"fg[\s\-–—_]*([0-9]{1,8})", text, re.IGNORECASE)
        if not m:
            return "Notiz"
        token = text[m.start():m.end()]
        neu = re.sub(r"[0-9]{1,8}", self.fg_nummer(m.group(1)), token)
        standard = m.start() == 0 and token == f"FG-{m.group(1)}"
        if standard:
            rest = text[m.end():].strip()
            return f"FG-{self.fg_nummer(m.group(1))}" + (" Notiz" if rest else "")
        return ("Notiz, " if m.start() > 0 else "") + neu + (" nachgetragen" if text[m.end():].strip() else "")


def pseudonymisiere_helper(p, h):
    sc = h.get("stateCache") or {}
    return {
        "id": p.helper_id(h.get("id")),
        "firstName": p.vorname(h.get("firstName") or ""),
        "lastName": p.nachname(h.get("lastName") or ""),
        "email": p.mail(h.get("email") or ""),
        "phone": p.telefon(h.get("phone") or "") or None,
        "additionalEmail1": p.mail(h.get("additionalEmail1") or "") or None,
        "additionalEmail2": p.mail(h.get("additionalEmail2") or "") or None,
        "adminRemarks": p.bemerkung(h.get("adminRemarks") or ""),
        "birthDate": p.geburtsdatum(h.get("birthDate")) or None,
        "groups": [{"id": g.get("id"), "name": g.get("name")} for g in (h.get("groups") or [])
                   if isinstance(g, dict)],
        "stateCache": {k: sc.get(k) for k in ("okAssignmentsNum", "nokAssignmentsNum",
                                             "confirmedAssignmentsNum", "reservedAssignmentsNum",
                                             "unconfirmedAssignmentsNum", "requestedValue",
                                             "plannedValue")},
    }


def pseudonymisiere_person(p, person):
    if not person:
        return None
    return {"id": p.helper_id(person.get("id")), "firstName": p.vorname(person.get("firstName") or ""),
            "lastName": p.nachname(person.get("lastName") or ""), "email": p.mail(person.get("email") or ""),
            "phone": None}


def pseudonymisiere_events(p, events):
    aus = []
    for i, ev in enumerate(events, 1):
        aus.append({"id": ev.get("id"), "name": f"Event {i}", "timeStart": ev.get("timeStart"),
                    "timeEnd": ev.get("timeEnd"), "online": ev.get("online"), "done": ev.get("done"),
                    "stateCache": ev.get("stateCache"), "category": ev.get("category"),
                    "shifts": [{"id": s.get("id"), "name": f"Schicht {j}", "startDateTime": s.get("startDateTime"),
                                "endDateTime": s.get("endDateTime"), "stateCache": s.get("stateCache")}
                               for j, s in enumerate(ev.get("shifts") or [], 1)]})
    return aus


def pseudonymisiere_assignments(p, assignments):
    return [{"id": a.get("id"), "status": a.get("status"), "value": a.get("value"),
             "plannedValue": a.get("plannedValue"), "hours": a.get("hours"),
             "role": {"id": (a.get("role") or {}).get("id"), "name": (a.get("role") or {}).get("name")},
             "helper": pseudonymisiere_person(p, a.get("helper")),
             "helpAsHelper": pseudonymisiere_person(p, a.get("helpAsHelper")),
             "responsible": a.get("responsible")} for a in assignments]


FAIRGATE_BEHALTEN = {"Mitgliedschaft"}
FAIRGATE_REGELN = {
    "Kontakt-ID Verein": "fg", "Primäre E-Mail": "mail", "E-Mail 2": "mail", "Mail 2": "mail",
    "E-Mail Eltern 1": "mail", "E-Mail Eltern 2": "mail", "Vorname": "vorname", "Nachname": "nachname",
    "Handy": "telefon", "Geburtsdatum": "geburtsdatum", "Kontakte": "kontaktnr",
}


def pseudonymisiere_fairgate(p, quelle, ziel):
    import openpyxl
    wb = openpyxl.load_workbook(quelle, read_only=True, data_only=True)
    ws = wb.active
    zeilen = ws.iter_rows(values_only=True)
    kopf = [str(c).strip() if c is not None else "" for c in next(zeilen, [])]
    aus = openpyxl.Workbook()
    ws2 = aus.active
    ws2.append(kopf)
    n = 0
    for zeile in zeilen:
        neu = []
        for name, wert in zip(kopf, zeile):
            regel = FAIRGATE_REGELN.get(name)
            if wert is None or wert == "":
                neu.append(None)
            elif name in FAIRGATE_BEHALTEN:
                neu.append(wert)
            elif regel == "fg":
                neu.append(int(p.fg_nummer(wert)))
            elif regel == "mail":
                neu.append(p.mail(str(wert)))
            elif regel == "vorname":
                neu.append(p.vorname(str(wert)))
            elif regel == "nachname":
                neu.append(p.nachname(str(wert)))
            elif regel == "telefon":
                neu.append(p.telefon(str(wert)))
            elif regel == "geburtsdatum":
                neu.append(p.geburtsdatum(wert if isinstance(wert, str) else wert.isoformat()))
            elif regel == "kontaktnr":
                neu.append(f"PER_{n + 1:04d}")
            else:
                neu.append(None)          # unbekannte Spalte: sicherheitshalber leeren
        ws2.append(neu)
        n += 1
    wb.close()
    aus.save(ziel)
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fairgate", help="Fairgate-Export (xlsx) zusätzlich pseudonymisieren")
    ap.add_argument("--nur-fairgate", help="nur den Fairgate-Export pseudonymisieren, kein API-Abruf")
    args = ap.parse_args()

    ZIEL.mkdir(parents=True, exist_ok=True)
    if SALZ_DATEI.exists():
        salz = SALZ_DATEI.read_text().strip()
    else:
        salz = hashlib.sha256(str(random.random()).encode()).hexdigest()[:16]
        SALZ_DATEI.write_text(salz)
    p = Pseudo(salz)
    bericht = []

    if not args.nur_fairgate:
        sys.path.insert(0, str(Path(__file__).parent))
        from cockpit.api_client import ApiClient
        import keyring
        key = keyring.get_password("helfereinsatz-api", "pfadi-winterthur-handball")
        if not key:
            sys.exit("Kein API-Key im Schlüsselbund — zuerst einmal  python3 start.py  ausführen.")
        client = ApiClient(key)
        print("Hole Portal-Daten …", flush=True)
        helpers = client.helpers()
        # Erst alle Helfer, dann Einsätze — so bekommen Personen in Einsätzen dieselben Kunstnamen
        pseudo_helpers = [pseudonymisiere_helper(p, h) for h in helpers]
        try:
            events = client.events()
            assignments = client.alle_assignments(events)
        except Exception as e:  # Einsätze sind optional (nur D6)
            events, assignments = [], []
            bericht.append(f"Einsätze nicht abgerufen: {type(e).__name__}")
        (ZIEL / "helpers.json").write_text(json.dumps(pseudo_helpers, ensure_ascii=False, indent=1), encoding="utf-8")
        (ZIEL / "events.json").write_text(json.dumps(pseudonymisiere_events(p, events), ensure_ascii=False, indent=1), encoding="utf-8")
        (ZIEL / "assignments.json").write_text(json.dumps(pseudonymisiere_assignments(p, assignments), ensure_ascii=False, indent=1), encoding="utf-8")
        bericht += [f"Helfer-Accounts: {len(helpers)}", f"Events: {len(events)}", f"Einsätze: {len(assignments)}"]

    quelle = args.fairgate or args.nur_fairgate
    if quelle:
        n = pseudonymisiere_fairgate(p, quelle, ZIEL / "fairgate.xlsx")
        bericht.append(f"Fairgate-Kontakte: {n}")

    bericht += [f"Ersetzungen: {p.zaehler}"]
    (ZIEL / "bericht.txt").write_text("\n".join(bericht) + "\n", encoding="utf-8")
    print("\n".join(bericht))
    print(f"\nFertig — Kunstdaten liegen in {ZIEL} (keine echten Namen, Mails, Telefonnummern, Notizen).")


if __name__ == "__main__":
    main()
