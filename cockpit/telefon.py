"""Telefonnummern: Fairgate erlaubt freien Text («079 123 45 67 (Mama)», «+41 79 …»), das Portal beim
Import nur Ziffern und Leerzeichen. Vergleich und Import arbeiten deshalb mit der normalisierten Form."""
import re

_ZIFFERN = re.compile(r"\d")


def ziffern(text):
    """Nur die Ziffern der ersten Nummer; «+41»/«0041» wird zu «0». Leer, wenn keine Nummer."""
    t = (text or "").strip()
    if not t:
        return ""
    # erste Nummer nehmen, falls mehrere («079 … / 078 …», «079 … oder 044 …»)
    t = re.split(r"\s*(?:/|;|,|\boder\b|\bund\b)\s*", t, maxsplit=1)[0]
    plus = t.startswith("+")
    z = "".join(_ZIFFERN.findall(t))
    if not z:
        return ""
    if plus or z.startswith("00"):
        z = z[2:] if z.startswith("00") else z
        z = "0" + z[2:] if z.startswith("41") else "00" + z          # Schweiz → 0…, Ausland → 00…
    return z


def gleich(a, b):
    """Zwei Nummern gelten als gleich, wenn ihre Ziffern gleich sind (Leerzeichen, Klammern,
    «Mama/Papa» und Landesvorwahl-Schreibweise spielen keine Rolle)."""
    return ziffern(a) == ziffern(b)


def fuer_import(text):
    """Nur Ziffern und Leerzeichen, in der üblichen Schweizer Gruppierung 079 123 45 67."""
    z = ziffern(text)
    if not z:
        return ""
    if len(z) == 10 and z.startswith("0"):
        return f"{z[:3]} {z[3:6]} {z[6:8]} {z[8:]}"
    return z


def sauber(text):
    """Wahr, wenn der Text so ins Portal darf (nur Ziffern und Leerzeichen)."""
    return re.fullmatch(r"[0-9 ]*", text or "") is not None
