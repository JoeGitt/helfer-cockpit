import pytest
from cockpit import telefon as tel

@pytest.mark.parametrize("text, erwartet", [
    ("079 123 45 67", "0791234567"),
    ("079 123 45 67 (Mama)", "0791234567"),
    ("Papa: 0791234567", "0791234567"),
    ("+41 79 123 45 67", "0791234567"),
    ("0041791234567", "0791234567"),
    ("+49 170 1234567", "00491701234567"),
    ("079 123 45 67 / 078 999 88 77", "0791234567"),
    ("079 123 45 67 oder 044 123 45 67 (Büro)", "0791234567"),
    ("Mama", ""), ("", ""), (None, ""),
])
def test_ziffern(text, erwartet):
    assert tel.ziffern(text) == erwartet

def test_gleich_ignoriert_schreibweise_und_zusaetze():
    assert tel.gleich("079 123 45 67 (Mama)", "0791234567")
    assert tel.gleich("+41 79 123 45 67", "079 123 45 67")
    assert not tel.gleich("079 123 45 67", "079 123 45 68")
    assert tel.gleich("", "") and not tel.gleich("079 123 45 67", "")

def test_fuer_import_nur_ziffern_und_leerzeichen():
    assert tel.fuer_import("+41 79 123 45 67 (Papa)") == "079 123 45 67"
    assert tel.fuer_import("044-123-45-67") == "044 123 45 67"
    assert tel.fuer_import("+49 170 1234567") == "00491701234567"
    assert tel.fuer_import("Mama") == ""
    for t in ("079 123 45 67", "0791234567", ""):
        assert tel.sauber(t)
    assert not tel.sauber("079 123 45 67 (Mama)") and not tel.sauber("+41 79")
