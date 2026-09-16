"""Ausgabedateien mit Personendaten nach Frist löschen (Spez 6.12). Erkannt werden nur Dateien,
die das Cockpit selbst erzeugt (Namensmuster mit Datum); das Datum im Namen zählt, nicht das
Änderungsdatum. Fremde Dateien, Regeln, gemerkte Antworten, Verlauf und «Updates» bleiben."""
import datetime
import re
from pathlib import Path

MUSTER = re.compile(r"^(?:import|handarbeitsliste|kontaktdaten-abweichungen|saeumige-[a-z]+|gesamtexport)"
                    r"-(\d{4}-\d{2}-\d{2})(?:-begruendung)?\.(?:xlsx|html|csv)$")


def abgelaufene(ausgabe_dir, tage, heute=None):
    if not tage or tage <= 0:
        return []
    heute = heute or datetime.date.today()
    treffer = []
    try:
        eintraege = list(Path(ausgabe_dir).iterdir())
    except OSError:
        return []
    for p in eintraege:
        m = MUSTER.match(p.name)
        if not m or not p.is_file():
            continue
        try:
            datum = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if (heute - datum).days > tage:
            treffer.append(p)
    return sorted(treffer)


def aufraeumen(ausgabe_dir, tage, heute=None):
    """Löscht abgelaufene Ausgabedateien, liefert die Namen der gelöschten."""
    geloescht = []
    for p in abgelaufene(ausgabe_dir, tage, heute):
        try:
            p.unlink(); geloescht.append(p.name)
        except OSError:
            pass
    return geloescht
