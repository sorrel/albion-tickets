"""Grounds for the calendar's location field."""
from datetime import date, datetime
from pathlib import Path

import pytest

from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.config import TZ
from albion_tickets.notices import Notice
from albion_tickets.run import _fingerprint, run_check, run_import
from albion_tickets.store import State, load, save
from albion_tickets.ticket_page import parse_ticket_page
from albion_tickets.venues import HOME, from_page, location

from .test_run import Fetcher, pages

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 20, 0, tzinfo=TZ)


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    return p


def page(name):
    return parse_ticket_page((FIX / f"ticket-page-{name}.txt").read_text(), date(2026, 11, 13), "saved page")


def fixture_locations(cal):
    return {n.title: n.location for n in cal.events.values() if n.key.startswith("fixture:")}


def test_from_page():
    assert from_page("MKM Stadium (Hull City)", "") == "MKM Stadium, Hull City"
    assert from_page("Away Stadium", "The fixture will be played at Olympic Stadium of Athens.") \
        == "Olympic Stadium of Athens"
    assert from_page("Away Stadium", "") is None
    assert from_page("ACCESS GUIDE", "") is None


def test_location_order():
    assert location("Aston Villa", False, "Villa Park, Aston Villa", {}) == "Villa Park, Birmingham"
    assert location("Panathinaikos", False, "Olympic Stadium of Athens", {}) == "Olympic Stadium of Athens"
    assert location("Panathinaikos", False, None, {"Panathinaikos": "Apostolos Nikolaidis"}) == "Apostolos Nikolaidis"
    assert location("AS Monaco", True, None, {}) == HOME
    assert location("Wrexham", True, "Wembley Stadium, London", {}) == "Wembley Stadium, London"
    assert location("Unknown FC", False, None, {}) == ""


def test_import_puts_grounds_on_fixture_events(state_path):
    cal = FakeCalendar()
    run_import(cal, [page("away"), page("home")], state_path, NOW, dry_run=False)
    where = fixture_locations(cal)
    assert where["⚽ Aston Villa v Albion"] == "Villa Park, Birmingham"
    assert where["⚽ Panathinaikos v Albion"] == "Olympic Stadium of Athens"
    assert where["⚽ Albion v AS Monaco"] == HOME
    assert not any(n.location for n in cal.events.values() if not n.key.startswith("fixture:"))


def test_checks_use_built_in_grounds_and_learnt_ones(state_path):
    s = load(state_path)
    s.venues["Fulham"] = "should not win over the table"
    save(s, state_path)
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    assert fixture_locations(cal)["⚽ Fulham v Albion"] == "Craven Cottage, London"


def test_import_learns_grounds_for_clubs_outside_the_table(state_path):
    run_import(FakeCalendar(), [page("away")], state_path, NOW, dry_run=False)
    state = load(state_path)
    assert state.venues["Panathinaikos"] == "Olympic Stadium of Athens"
    assert state.matches["2026-27-panathinaikos-a-uefa-conference-league"].venue == "Olympic Stadium of Athens"


def test_fingerprint_unchanged_without_a_location():
    n = Notice("sale:x", "t", NOW, NOW, [], "notes")
    import hashlib, json
    old = hashlib.sha256(json.dumps(["t", NOW.isoformat(), NOW.isoformat(), [], "notes"]).encode()).hexdigest()[:16]
    assert _fingerprint(n) == old
