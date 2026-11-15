"""The three-weekly nudge to save the ticket pages again."""
from datetime import datetime

import pytest

from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.config import TZ
from albion_tickets.fetch import FetchResult
from albion_tickets.importing import run_import
from albion_tickets.notices import IMPORT_KEY, import_due
from albion_tickets.run import run_check
from albion_tickets.store import MatchRecord, State, load, save
from albion_tickets.ticket_page import PageResult

NOV_15 = datetime(2026, 11, 15, 10, tzinfo=TZ)


def offline(url):
    return FetchResult(None, "", url, "offline")


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", [])
    p = tmp_path / "state.json"
    save(State(points=184), p)
    return p


def reminder(cal):
    return next(n for n in cal.events.values() if n.key == IMPORT_KEY)


def test_due_three_weeks_on_at_7pm_then_weekly_until_done():
    assert import_due(NOV_15, NOV_15) == datetime(2026, 12, 6, 19, tzinfo=TZ)
    assert import_due(NOV_15, datetime(2026, 12, 7, 12, tzinfo=TZ)) == datetime(2026, 12, 6, 19, tzinfo=TZ)
    assert import_due(NOV_15, datetime(2026, 12, 8, 12, tzinfo=TZ)) == datetime(2026, 12, 13, 19, tzinfo=TZ)


def test_an_import_records_itself_and_sets_the_reminder(state_path):
    cal = FakeCalendar()
    run_import(cal, [PageResult([], [])], state_path, NOV_15, dry_run=False)
    assert load(state_path).last_import == NOV_15.isoformat()
    n = reminder(cal)
    assert n.start == datetime(2026, 12, 6, 19, tzinfo=TZ) and n.alarms == [n.start]
    assert "albion import" in n.notes

    later = datetime(2026, 12, 1, 10, tzinfo=TZ)  # importing again moves the one event on
    run_import(cal, [PageResult([], [])], state_path, later, dry_run=False)
    assert [n.start for n in cal.events.values() if n.key == IMPORT_KEY] == [datetime(2026, 12, 22, 19, tzinfo=TZ)]


def test_a_dry_run_import_records_nothing(state_path):
    run_import(FakeCalendar(), [PageResult([], [])], state_path, NOV_15, dry_run=True)
    assert load(state_path).last_import is None


def test_checks_keep_it_and_older_imports_count(state_path):
    """Imports made before this was recorded are dated by their matches."""
    s = load(state_path)
    s.matches["2026-27-brentford-a-premier-league"] = MatchRecord(
        kickoffs=[("2027-01-16T15:00:00+00:00", "x")], last_seen="2026-11-14T09:00:00+00:00",
        summary={"opponent": "Brentford", "home": False, "source": "import"})
    save(s, state_path)
    cal = FakeCalendar()
    run_check(cal, offline, state_path, NOV_15, dry_run=False)
    assert reminder(cal).start == datetime(2026, 12, 5, 19, tzinfo=TZ)
    assert load(state_path).last_import == "2026-11-14T09:00:00+00:00"


def test_no_reminder_before_any_import(state_path):
    cal = FakeCalendar()
    run_check(cal, offline, state_path, NOV_15, dry_run=False)
    assert not any(n.key == IMPORT_KEY for n in cal.events.values())
