import json
import subprocess
from datetime import datetime

from albion_tickets.calendar_app import FakeCalendar, MacCalendar, alarm_minutes
from albion_tickets.config import TZ
from albion_tickets.notices import Notice


def at(m, d, h=9, mi=0):
    return datetime(2026, m, d, h, mi, tzinfo=TZ)


N = Notice("sale:k", "🎟️ Brentford away: your sale", at(12, 4), at(12, 4, 9, 15),
           [at(12, 3, 19), at(12, 4, 8, 30)], "notes")


def test_fake_upsert_then_update_keeps_uid():
    cal = FakeCalendar()
    uid = cal.upsert(N, None)
    assert cal.upsert(N, uid) == uid
    assert len(cal.events) == 1 and cal.events[uid].title == N.title


def test_fake_upsert_with_vanished_uid_creates_new():
    cal = FakeCalendar()
    assert cal.upsert(N, "gone") != "gone"


def test_fake_remove_missing_is_noop():
    FakeCalendar().remove("nothing")


def test_alarm_minutes_relative_to_start():
    assert alarm_minutes(N) == [-840, -30]


class Done:
    def __init__(self, out):
        self.returncode, self.stdout, self.stderr = 0, out, ""


def test_mac_payload_goes_via_stdin(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["input"] = args, kw["input"]
        return Done("UID-1\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert MacCalendar("Albion tickets").upsert(N, None) == "UID-1"
    assert all("Brentford" not in a for a in seen["args"])
    payload = json.loads(seen["input"])
    assert payload["op"] == "upsert" and payload["title"] == N.title
    assert payload["alarms"] == [-840, -30] and payload["calendar"] == "Albion tickets" and payload["location"] == ""
    assert payload["start"] == int(at(12, 4).timestamp() * 1000)


def test_mac_missing_calendar_message(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done("missing\n"))
    msg = MacCalendar("Albion tickets").check_ready()
    assert msg == 'Calendar "Albion tickets" not found — create it in Calendar.app under your iCloud account'


def test_mac_failure_raises(monkeypatch):
    class Bad(Done):
        def __init__(self):
            super().__init__("")
            self.returncode, self.stderr = 1, "execution error"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Bad())
    import pytest
    from albion_tickets.calendar_app import CalendarError
    with pytest.raises(CalendarError):
        MacCalendar("Albion tickets").upsert(N, None)
