import json
import sys
from datetime import datetime

import pytest

from albion_tickets import calendar_app
from albion_tickets.calendar_app import CalendarError, Change, FakeCalendar, MacCalendar, alarm_minutes, remove, upsert
from albion_tickets.config import TZ
from albion_tickets.notices import Notice


def at(m, d, h=9, mi=0):
    return datetime(2026, m, d, h, mi, tzinfo=TZ)


N = Notice("sale:k", "🎟️ Brentford away: your sale", at(12, 4), at(12, 4, 9, 15),
           [at(12, 3, 19), at(12, 4, 8, 30)], "notes")
F = Notice("fixture:k", "⚽ Fulham v Albion", at(12, 26, 15), at(12, 26, 17), [], "u",
           location="Craven Cottage, Stevenage Road, London SW6 6HH, England", geo=(51.47485, -0.22164))


def test_fake_upsert_then_update_keeps_uid():
    cal = FakeCalendar()
    uid = upsert(cal, N, None)
    assert upsert(cal, N, uid) == uid and len(cal.events) == 1


def test_fake_upsert_with_vanished_uid_creates_new():
    cal = FakeCalendar()
    assert upsert(cal, N, "gone") != "gone"


def test_fake_remove_missing_is_noop():
    remove(FakeCalendar(), "nothing")


def test_alarm_minutes_relative_to_start():
    assert alarm_minutes(N) == [-840, -30]


def stand_in(tmp_path, body: str) -> MacCalendar:
    """A MacCalendar whose script is a small Python program: never the real calendar."""
    script = tmp_path / "fake.py"
    script.write_text("import json, sys, time\nreq = json.load(sys.stdin)\n" + body)
    return MacCalendar("Albion tickets", [sys.executable, str(script)])


def test_mac_sends_one_batch_with_location_and_pin(tmp_path):
    seen = tmp_path / "seen.json"
    cal = stand_in(tmp_path, f"open({str(seen)!r}, 'w').write(json.dumps(req))\n"
                             "for i, op in enumerate(req['ops']):\n"
                             "    print(json.dumps({'ok': True, 'uid': f'id{i}'}), flush=True)\n")
    assert cal.apply([Change(None, N), Change("old", F), Change("x")]) == ["id0", "id1", "id2"]
    req = json.loads(seen.read_text())
    assert req["calendar"] == "Albion tickets"
    sale, fixture, gone = req["ops"]
    assert sale["op"] == "upsert" and sale["alarms"] == [-840, -30] and sale["geo"] is None
    assert sale["start"] == int(at(12, 4).timestamp() * 1000)
    assert fixture["uid"] == "old" and fixture["geo"] == [51.47485, -0.22164]
    assert fixture["location"].startswith("Craven Cottage")
    assert gone == {"op": "remove", "uid": "x"}


def test_mac_keeps_what_finished_when_a_batch_stalls(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_app, "BASE_TIMEOUT_S", 1)
    monkeypatch.setattr(calendar_app, "PER_CHANGE_S", 0)
    cal = stand_in(tmp_path, "print(json.dumps({'ok': True, 'uid': 'made'}), flush=True)\ntime.sleep(30)\n")
    first, second = cal.apply([Change(None, N), Change(None, F)])
    assert first == "made"  # recorded, so never created twice
    assert isinstance(second, CalendarError) and "did not finish" in str(second)


def test_mac_reports_each_failure(tmp_path):
    cal = stand_in(tmp_path, "print(json.dumps({'ok': False, 'error': 'event x is in another calendar'}))\n")
    [result] = cal.apply([Change("x")])
    assert isinstance(result, CalendarError) and "another calendar" in str(result)
    with pytest.raises(CalendarError):
        remove(cal, "x")


def test_mac_missing_calendar_message(tmp_path):
    cal = stand_in(tmp_path, "print(json.dumps({'ok': False, 'error': 'missing'}))\n")
    assert "not found" in cal.check_ready()


def test_mac_no_access_message(tmp_path):
    cal = stand_in(tmp_path, "print(json.dumps({'ok': False, 'error': 'no full calendar access: allow it'}))\n")
    assert "no full calendar access" in cal.check_ready()


def test_mac_script_crash_is_an_error_not_a_hang(tmp_path):
    cal = stand_in(tmp_path, "sys.stderr.write('boom'); sys.exit(1)\n")
    [result] = cal.apply([Change(None, N)])
    assert isinstance(result, CalendarError) and "boom" in str(result)


def test_calendar_script_never_touches_other_calendars():
    js = calendar_app.SCRIPT.read_text()
    assert "in another calendar: refusing to touch it" in js
    assert "calendarItemsWithExternalIdentifier" in js and "calendarIdentifier" in js


class LostReply(FakeCalendar):
    """Saves every event but, the first time, the reply never arrives (the run was cut short)."""

    def __init__(self):
        super().__init__()
        self.lose = True

    def apply(self, changes):
        results = super().apply(changes)
        if self.lose:
            self.lose = False
            return [CalendarError("the calendar did not finish within 150 s") for _ in results]
        return results


def test_a_lost_reply_never_leaves_a_duplicate(tmp_path, monkeypatch):
    """The Hull bug: written, reply lost, rewritten with a new title → must still be one event."""
    from dataclasses import replace

    cal = LostReply()
    [lost] = cal.apply([Change(None, F)])
    assert isinstance(lost, CalendarError) and len(cal.events) == 1  # saved, but we never heard
    uid = upsert(cal, replace(F, title="⚽ Fulham v Albion (time not confirmed)"), None)
    assert list(cal.events) == [uid] and cal.events[uid].title.endswith("(time not confirmed)")


def test_mac_sends_each_events_key(tmp_path):
    seen = tmp_path / "seen.json"
    cal = stand_in(tmp_path, f"open({str(seen)!r}, 'w').write(json.dumps(req))\n"
                             "print(json.dumps({'ok': True, 'uid': 'id0'}), flush=True)\n")
    cal.apply([Change(None, F)])
    assert json.loads(seen.read_text())["ops"][0]["key"] == "fixture:k"
