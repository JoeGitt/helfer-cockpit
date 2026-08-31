import json
from pathlib import Path
from cockpit.model import classify, build_mitglieder
from cockpit.checks import run_checks

FIXTURES = Path(__file__).parent / "fixtures"

def _setup(assignments=True):
    helpers = json.loads((FIXTURES / "helpers.json").read_text(encoding="utf-8"))
    accounts = [classify(h) for h in helpers]
    mitglieder = build_mitglieder(accounts)
    asg = json.loads((FIXTURES / "assignments.json").read_text(encoding="utf-8")) if assignments else None
    return run_checks(accounts, mitglieder, asg)

def _codes(hinweise):
    return sorted({h.code for h in hinweise})

def test_alle_erwarteten_checks_feuern():
    assert _codes(_setup()) == ["D1", "D2", "D4", "D5", "D6", "D7", "D8"]
    # D3 (Doppel-Mitglied) und D9 (unklassifiziert) sind im Fixture nicht enthalten

def test_d1_fg_ohne_mitglied():
    d1 = [h for h in _setup() if h.code == "D1"]
    assert len(d1) == 1 and "Marc Steiner" in d1[0].betroffene and d1[0].schweregrad == "kritisch"

def test_d2_zweitaccount_mit_zielwert():
    d2 = [h for h in _setup() if h.code == "D2"]
    assert len(d2) == 1 and "Rita Gerber" in d2[0].betroffene

def test_d5_unbekannte_mit_einsatz():
    d5 = [h for h in _setup() if h.code == "D5"]
    assert len(d5) == 1 and "Dario Ackermann" in d5[0].betroffene

def test_d5_unbekannte_mit_nur_nok():
    # Synthetischer Test: Unbekannte mit EINZIGEM Signal num_nok > 0
    unbekannte_nok = classify({
        "id": 999,
        "firstName": "Test",
        "lastName": "NOK",
        "email": "test@example.ch",
        "phone": None,
        "additionalEmail1": None,
        "additionalEmail2": None,
        "adminRemarks": "",
        "birthDate": None,
        "groups": [{"id": 4, "name": "Unbekannte"}],
        "stateCache": {
            "okAssignmentsNum": 0,
            "nokAssignmentsNum": 1,
            "confirmedAssignmentsNum": 0,
            "reservedAssignmentsNum": 0,
            "unconfirmedAssignmentsNum": 0,
            "requestedValue": 0,
            "plannedValue": 0
        }
    })
    hinweise = run_checks([unbekannte_nok], [], None)
    d5 = [h for h in hinweise if h.code == "D5"]
    assert len(d5) == 1 and "Test NOK" in d5[0].betroffene

def test_d6_vergessene_gutschrift():
    d6 = [h for h in _setup() if h.code == "D6"]
    assert len(d6) == 1 and "Reto Brunner" in d6[0].betroffene
    assert not any("Petra Vogt" in h.betroffene for h in d6)   # Gutschrift benutzt → kein Hinweis

def test_d6_entfaellt_ohne_assignments():
    assert "D6" not in _codes(_setup(assignments=False))

def test_d3_und_d9():
    helpers = json.loads((FIXTURES / "helpers.json").read_text(encoding="utf-8"))
    doppel = dict(helpers[0]); doppel["id"] = 999
    fremd = dict(helpers[0]); fremd["id"] = 998; fremd["adminRemarks"] = ""; fremd["groups"] = [{"id": 9, "name": "Foodbox"}]
    accounts = [classify(h) for h in helpers + [doppel, fremd]]
    codes = _codes(run_checks(accounts, build_mitglieder(accounts), None))
    assert "D3" in codes and "D9" in codes
