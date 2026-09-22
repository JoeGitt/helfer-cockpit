import subprocess
import sys
from pathlib import Path
from cockpit import changelog, updater
from cockpit.version import VERSION

WURZEL = Path(__file__).resolve().parent.parent


def test_aktuelle_version_hat_versionshinweise():
    # Ein Release ohne Hinweise würde der Release-Workflow ohnehin abweisen — hier früher auffallen
    e = changelog.lies()
    assert e and e[0]["version"] == VERSION and e[0]["punkte"], "Neueste Version zuoberst in cockpit/CHANGELOG.md eintragen"


def test_versionen_absteigend_und_eindeutig():
    versionen = [e["version"] for e in changelog.lies()]
    assert len(versionen) == len(set(versionen))
    assert versionen == sorted(versionen, key=updater.version_tuple, reverse=True)


def test_parser_und_abschnitt():
    text = "# Titel\n\n## 2.0.1 — 01.01.2027\n- Erster Punkt\n  mit Fortsetzung\n- Zweiter\n\n## 2.0.0 - 31.12.2026\n- Alt\n"
    e = changelog.lies(text)
    assert [x["version"] for x in e] == ["2.0.1", "2.0.0"] and e[0]["datum"] == "01.01.2027"
    assert e[0]["punkte"] == ["Erster Punkt mit Fortsetzung", "Zweiter"]
    assert changelog.abschnitt("2.0.1", e) == "- Erster Punkt mit Fortsetzung\n- Zweiter"
    assert changelog.abschnitt("9.9.9", e) == ""


def test_release_notes_skript_liefert_abschnitt():
    r = subprocess.run([sys.executable, str(WURZEL / "packaging" / "release_notes.py")], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().startswith("- ")


def test_update_sammelt_hinweise_seit_installierter_version():
    def rel(v, asset=True, body=None):
        return {"tag_name": f"v{v}", "body": body or f"- Punkt {v}",
                "assets": [{"name": f"HelferCockpit-{v}-windows.zip", "browser_download_url": f"https://x/{v}.zip", "size": 1}] if asset else []}
    k = updater.auswerten([rel("2.1.16"), rel("2.1.15"), rel("2.1.14"), rel("2.1.13"), {**rel("2.2.0"), "draft": True}], aktuell="2.1.13")
    assert k["version"] == "2.1.16" and k["url"].endswith("2.1.16.zip")
    assert [h["version"] for h in k["hinweise"]] == ["2.1.16", "2.1.15", "2.1.14"]
    assert updater.auswerten([rel("2.1.13", asset=False)], aktuell="2.1.0") is None
