"""Tests for the final review's findings (C1, I1–I7)."""
import functools
import gzip
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from albion_tickets import fetch
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.config import BASE_URL, TZ
from albion_tickets.fetch import FetchResult
from albion_tickets.model import Match, Stage, Status
from albion_tickets.parse_article import parse_text
from albion_tickets.parse_stages import parse_status
from albion_tickets.rules import decide
from albion_tickets.run import run_check
from albion_tickets.store import State, observe, save

FIX = Path(__file__).parent / "fixtures"
ART = BASE_URL + "/media-article/"
SPURS = ART + "tottenham-hotspur-ticket-information"


@functools.cache
def page(name):
    return gzip.open(FIX / name, "rt").read()


def at(m, d, h=9, mi=0, y=2026):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


class Fetcher:
    def __init__(self, table):
        self.table = table

    def __call__(self, url):
        if url in self.table:
            return FetchResult(200, self.table[url], url, None)
        return FetchResult(404, "", url, "HTTPError 404")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    st = State(points=184)
    st.articles[SPURS] = {"title": "Tottenham Hotspur ticket information", "published": "2026-11-05", "matches": []}
    save(st, p)
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", [])
    return p


def spurs_table(edit=None):
    html = page("article-tottenham-hotspur-ticket-information.html.gz")
    if edit:
        html = html.replace(*edit)
    return {SPURS: html}


def events_by_kind(cal):
    out = {}
    for n in cal.events.values():
        out.setdefault(n.key.split(":")[0], []).append(n)
    return out


# C1 — an edit that breaks the user's stage line keeps the sale reminder and alerts in the future
def test_unreadable_edit_keeps_sale_and_check_alerts_soon(setup):
    cal = FakeCalendar()
    run_check(cal, Fetcher(spurs_table()), setup, at(11, 9), dry_run=False)
    assert "sale" in events_by_kind(cal)
    edited = spurs_table(("All STHs/1901 Club members: Fri 13 Nov", "All STHs/1901 Club members: Thu 13 Nov"))
    now = at(11, 12, 21)
    run_check(cal, Fetcher(edited), setup, now, dry_run=False)
    kinds = events_by_kind(cal)
    assert "sale" in kinds, "the existing sale reminder must survive"
    (check,) = kinds["check"]
    assert check.start >= now and check.alarms and check.alarms[0] >= now
    assert check.start <= now + timedelta(minutes=10)  # a stage opens before next morning: straight away


# I1 — a misprinted bracket line above the user means "check this", not a later stage
def test_unreadable_sth_line_makes_outcome_unreadable():
    stages = [Stage("STHs with 300+pts", "sth", 300, False, at(11, 10), True),
              Stage("STHs with 208+pts", "sth", 208, False, at(11, 12), True),
              Stage("All STHs", "sth", None, False, at(11, 13), True)]
    m = Match("k", "Spurs", False, "Premier League", at(12, 29, 19, 30), True, stages, Status(), 5, "u",
              ["STHs/1901 Club members with 239+pts: Thu 11 Nov"])
    assert decide(m, 240, at(11, 1), None).kind == "unreadable"


# I2 — check-this events don't move or re-alert across days
def test_check_this_stable_across_days(setup):
    cal = FakeCalendar()
    broken = spurs_table(("All STHs/1901 Club members: Fri 13 Nov", "All STHs/1901 Club members: Thu 13 Nov"))
    run_check(cal, Fetcher(broken), setup, at(11, 1, 20), dry_run=False)
    first = list(cal.calls)
    r2 = run_check(cal, Fetcher(broken), setup, at(11, 2, 20), dry_run=False)
    r3 = run_check(cal, Fetcher(broken), setup, at(11, 3, 20), dry_run=False)
    assert cal.calls == first and r2.updated == r3.updated == []


def test_article_without_payload_check_stable_across_days(setup):
    cal = FakeCalendar()
    table = {SPURS: "<html>nothing here</html>"}
    run_check(cal, Fetcher(table), setup, at(11, 6, 20), dry_run=False)
    first = list(cal.calls)
    run_check(cal, Fetcher(table), setup, at(11, 7, 20), dry_run=False)
    assert cal.calls == first


# I3 — a status suffix in a heading doesn't change the match
def test_heading_suffix_keeps_key():
    t1 = "Leeds v Albion\nSaturday 13 March - kick-off 3pm\nAll STHs/1901 Club members: Tue 2 Feb"
    t2 = "Leeds v Albion - SOLD OUT\nSaturday 13 March - kick-off 3pm\nAll STHs/1901 Club members: Tue 2 Feb"
    k1 = parse_text(t1, "u", "t", at(1, 20, y=2027).date()).matches[0]
    k2 = parse_text(t2, "u", "t", at(1, 20, y=2027).date()).matches[0]
    assert k1.key == k2.key and k2.opponent == "Leeds"


# I3 — a match that disappears from a readable article leaves no orphans, and asks for a look
def test_match_dropped_from_article_retires_events_and_asks(setup):
    cal = FakeCalendar()
    run_check(cal, Fetcher(spurs_table()), setup, at(11, 9), dry_run=False)
    renamed = spurs_table(("Tottenham Hotspur v Albion", "Spurs v Albion"))
    run_check(cal, Fetcher(renamed), setup, at(11, 9, 11), dry_run=False)
    fixtures = [n for n in cal.events.values() if n.key.startswith("fixture:")]
    assert [n.title for n in fixtures] == ["⚽ Spurs v Albion"]
    assert any(n.key.startswith("check:") for n in cal.events.values())


# I4 — a redirect to another host is refused before it is followed
def test_redirect_off_main_site_refused():
    handler = fetch.SameSiteRedirects()
    req = urllib.request.Request(BASE_URL + "/media-article/x")
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(req, None, 301, "Moved", {}, "https://tickets.brightonandhovealbion.com/")
    assert handler.redirect_request(req, None, 301, "Moved", {}, BASE_URL + "/media-article/y") is not None


# I5 — boilerplate mentioning "sold out" is not a sell-out
def test_boilerplate_sold_out_ignored():
    text = ("Pricing:\nAdult: £30\nIf this fixture becomes sold out, a ticket exchange may operate and "
            "supporters will be informed via the club's channels in due course.")
    assert not parse_status(text, None, None).sold_out_label_seen


def test_line_level_sold_out_counts():
    assert parse_status("Tickets for this fixture are now sold out.", None, None).sold_out_label_seen
    assert parse_status("SOLD OUT", None, None).sold_out_label_seen


def test_sold_label_present_before_sales_never_counts_without_stage():
    stages = [Stage("All STHs", "sth", None, False, at(10, 30), True)]
    m = Match("k", "X", False, "Premier League", at(12, 5), True, stages, Status(sold_out_label_seen=True), 5, "u")
    st = State()
    observe(st, m, at(10, 30), at(10, 20))
    observe(st, m, at(10, 30), at(10, 31))
    assert st.matches["k"].first_sold_out_seen is None


# I6 — no "sale moved" alert for a sale that is over
def test_no_sale_moved_for_past_sales():
    stages = [Stage("All STHs", "sth", None, False, at(11, 13), True)]
    m = Match("k", "X", False, "Premier League", at(12, 29), True, stages, Status(), 5, "u")
    st = State()
    observe(st, m, at(11, 13), at(11, 9))
    assert observe(st, m, at(11, 11), at(11, 20)) == []


# I7 — a listing with no recognisable items is an error, and a broken article doesn't stop the run
def test_listing_without_items_is_an_error(setup, monkeypatch):
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", ["/all-latest-news"])
    table = spurs_table()
    table[BASE_URL + "/all-latest-news"] = "<html>redesigned</html>"
    report = run_check(FakeCalendar(), Fetcher(table), setup, at(11, 9), dry_run=False)
    assert any("no articles found" in e for e in report.errors)


def test_parse_crash_is_reported_not_fatal(setup, monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad date")
    monkeypatch.setattr("albion_tickets.run.parse_article", boom)
    report = run_check(FakeCalendar(), Fetcher(spurs_table()), setup, at(11, 9), dry_run=False)
    assert any("bad date" in e for e in report.errors)


def test_repeated_failure_puts_one_attention_event_in_calendar(setup, monkeypatch):
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", ["/all-latest-news"])
    cal = FakeCalendar()
    down = Fetcher({})
    for h in range(7, 19, 2):  # six failing runs in a day
        run_check(cal, down, setup, at(11, 9, h), dry_run=False)
    attention = [n for n in cal.events.values() if n.key.startswith("attention:")]
    assert len(attention) == 1 and attention[0].alarms
