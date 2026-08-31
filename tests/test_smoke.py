import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

def test_fixtures_laden():
    helpers = json.loads((FIXTURES / "helpers.json").read_text(encoding="utf-8"))
    assignments = json.loads((FIXTURES / "assignments.json").read_text(encoding="utf-8"))
    assert len(helpers) == 10
    assert len(assignments) == 3
    assert helpers[0]["stateCache"]["requestedValue"] == 2
