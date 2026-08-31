import json
from cockpit.protokoll import logge, lese

def test_logge_und_lese(tmp_path):
    pfad = tmp_path / "protokoll.jsonl"
    logge(pfad, "api-abruf", {"accounts": 453, "hinweise": 2})
    logge(pfad, "abgleich", {"neueintritte": 2})
    eintraege = lese(pfad)
    assert eintraege[0]["aktion"] == "abgleich"      # neueste zuerst
    assert eintraege[1]["accounts"] == 453
    assert "zeit" in eintraege[0]

def test_lese_ohne_datei(tmp_path):
    assert lese(tmp_path / "leer.jsonl") == []


def test_lese_ueberspringt_korrupte_zeilen(tmp_path):
    pfad = tmp_path / "protokoll.jsonl"
    logge(pfad, "api-abruf", {"accounts": 1})
    with pfad.open("a", encoding="utf-8") as f:
        f.write("{das ist kaputtes json\n")
    logge(pfad, "abgleich", {"neueintritte": 1})
    eintraege = lese(pfad)
    assert [e["aktion"] for e in eintraege] == ["abgleich", "api-abruf"]
