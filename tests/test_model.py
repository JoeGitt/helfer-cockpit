import pytest
from cockpit.model import normalize_fg

@pytest.mark.parametrize("text,erwartet", [
    ("FG-2417", ("FG-2417", False)),
    ("FG-2417 zweiter Account", ("FG-2417", False)),
    ("fg 2417", ("FG-2417", True)),            # Schreibweise abweichend
    ("fg-2417", ("FG-2417", True)),            # Kleinschreibung
    ("Zahlt bar, FG-2417 nachgetragen", ("FG-2417", True)),  # nicht am Anfang
    ("FG–2417", ("FG-2417", True)),            # Gedankenstrich
    ("", (None, False)),
    (None, (None, False)),
    ("Unbekannt, kein Vereinsbezug", (None, False)),
])
def test_normalize_fg(text, erwartet):
    assert normalize_fg(text) == erwartet

def test_normalize_fg_nimmt_ersten_treffer():
    assert normalize_fg("FG-1 und FG-2")[0] == "FG-1"
