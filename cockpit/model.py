"""Datenmodell: FG-Normalisierung, Typ-Erkennung, Aggregation, Status.

Regeln gemäss SPEZIFIKATION-helfer-cockpit-2.md Kap. 4+5. Die Erkennung
liegt bewusst komplett in diesem Modul (eine Stelle für spätere Regel-Wechsel).
"""
import re

# FG irgendwo in der Bemerkung erkennen (Spez. Kap. 4): case-insensitiv,
# Trennzeichen-tolerant. Eine nicht erkannte Nummer wäre ein stiller Fehler.
_FG_MUSTER = re.compile(r"fg[\s\-–—_]*([0-9]{1,8})", re.IGNORECASE)


def normalize_fg(text):
    if not text:
        return (None, False)
    m = _FG_MUSTER.search(text)
    if not m:
        return (None, False)
    fg = f"FG-{m.group(1)}"
    standard = m.start() == 0 and text[m.start():m.end()] == fg
    return (fg, not standard)
