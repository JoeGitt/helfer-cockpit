import pytest
from cockpit.api_client import ApiClient, ApiFehler

def _fake_hole(antworten):
    """antworten: dict Pfad -> JSON-Dict. Unbekannter Pfad -> KeyError."""
    def hole(pfad):
        return antworten[pfad]
    return hole

def test_helpers_holt_alle_seiten():
    c = ApiClient("key", hole=_fake_hole({
        "helpers/1": {"pageNo": 1, "pagesNum": 2, "entries": [{"id": 1}]},
        "helpers/2": {"pageNo": 2, "pagesNum": 2, "entries": [{"id": 2}]},
    }))
    assert [h["id"] for h in c.helpers()] == [1, 2]

def test_assignments_pro_event():
    c = ApiClient("key", hole=_fake_hole({
        "events/1": {"pageNo": 1, "pagesNum": 1, "entries": [{"id": 7}, {"id": 8}]},
        "helperassignments/7/1": {"pageNo": 1, "pagesNum": 1, "entries": [{"id": 70}]},
        "helperassignments/8/1": {"pageNo": 1, "pagesNum": 1, "entries": [{"id": 80}]},
    }))
    events = c.events()
    assert [a["id"] for a in c.alle_assignments(events)] == [70, 80]

def test_format_fehler_bei_unbekannter_struktur():
    c = ApiClient("key", hole=_fake_hole({"helpers/1": {"unerwartet": True}}))
    with pytest.raises(ApiFehler) as e:
        c.helpers()
    assert e.value.art == "format"


def test_format_fehler_bei_nicht_numerischem_pagesnum():
    c = ApiClient("key", hole=_fake_hole({
        "helpers/1": {"pageNo": 1, "pagesNum": "viele", "entries": [{"id": 1}]},
    }))
    with pytest.raises(ApiFehler) as e:
        c.helpers()
    assert e.value.art == "format"
