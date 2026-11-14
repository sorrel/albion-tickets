import functools
import gzip
from datetime import datetime
from pathlib import Path

import pytest

from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.config import BASE_URL, TZ
from albion_tickets.fetch import FetchResult
from albion_tickets.run import run_check
from albion_tickets.store import State, load, save

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 20, 0, tzinfo=TZ)
ART = BASE_URL + "/media-article/"


@functools.cache
def page(name):
    return gzip.open(FIX / name, "rt").read()


def pages():
    return {
        BASE_URL + "/all-latest-news": page("listing-all.html.gz"),
        ART + "fulham-ticket-information": page("article-fulham-ticket-information.html.gz"),
        ART + "tottenham-hotspur-ticket-information": page("article-tottenham-hotspur-ticket-information.html.gz"),
        ART + "newcastle-united-sold-out-ticket-exchange-now-open":
            page("article-newcastle-united-sold-out-ticket-exchange-now-open.html.gz"),
    }


class Fetcher:
    def __init__(self, table, fail=False):
        self.table, self.fail, self.urls = table, fail, []

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            return FetchResult(None, "", url, "timed out")
        if url in self.table:
            return FetchResult(200, self.table[url], url, None)
        return FetchResult(404, "", url, "HTTPError 404")


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    return p


def test_end_to_end_creates_sale_fixture_and_points_events(state_path):
    cal = FakeCalendar()
    report = run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    titles = {n.key.split(":")[0] + ":" + n.title for n in cal.events.values()}
    assert "fixture:Fulham v Albion" in titles
    assert "fixture:Tottenham Hotspur v Albion" in titles
    # NOW is the evening of Fri 13 Nov: the Fulham and Spurs sales are over, and no points are due yet
    assert not any(t.startswith("sale:") for t in titles)
    assert not any(t.startswith("points:") for t in titles)
    assert not any("Newcastle" in t for t in titles)  # home Premier League: ignored
    assert any("manchester-united-ticket-information" in e for e in report.errors)  # 404 in this fixture set
    st = load(state_path)
    assert st.events and all("uid" in v for v in st.events.values())


def test_second_identical_run_changes_nothing(state_path):
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    before = list(cal.calls)
    report = run_check(cal, Fetcher(pages()), state_path, NOW.replace(hour=22), dry_run=False)
    assert cal.calls == before
    assert report.created == report.updated == report.removed == report.changes == []


def test_failed_fetch_removes_nothing(state_path):
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    events = dict(cal.events)
    report = run_check(cal, Fetcher(pages(), fail=True), state_path, NOW.replace(hour=22), dry_run=False)
    assert cal.events == events and report.removed == []
    assert report.errors


def test_changed_article_moves_event_and_adds_change_notice(state_path):
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    table = pages()
    url = ART + "fulham-ticket-information"
    table[url] = table[url].replace("Saturday 26 December - kick-off 3pm", "Sunday 27 December - kick-off 12:30pm")
    report = run_check(cal, Fetcher(table), state_path, NOW.replace(hour=22), dry_run=False)
    fixture = next(n for n in cal.events.values() if n.title == "Fulham v Albion")
    assert fixture.start == datetime(2026, 12, 27, 12, 30, tzinfo=TZ)
    moved = [n for n in cal.events.values() if n.key.startswith("kickoff_moved:")]
    assert len(moved) == 1 and moved[0].title == "⚠️ Fulham: kick-off moved Sat 26 Dec 3pm → Sun 27 Dec 12.30pm"
    assert report.changes


def test_dry_run_writes_nothing(state_path):
    cal = FakeCalendar()
    before = state_path.read_text()
    report = run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=True)
    assert cal.calls == [] and state_path.read_text() == before
    assert report.created
    assert not (state_path.parent / "snapshots").exists()


def test_missing_points_aborts(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    fetcher = Fetcher(pages())
    report = run_check(FakeCalendar(), fetcher, tmp_path / "state.json", NOW, dry_run=False)
    assert report.errors == ["Set your points first: albion points <n>"]
    assert fetcher.urls == []


def test_calendar_not_ready_aborts(state_path):
    class NotReady(FakeCalendar):
        def check_ready(self):
            return "no calendar"

    fetcher = Fetcher(pages())
    report = run_check(NotReady(), fetcher, state_path, NOW, dry_run=False)
    assert report.errors == ["no calendar"] and fetcher.urls == []


def test_never_requests_ticket_site(state_path):
    fetcher = Fetcher(pages())
    run_check(FakeCalendar(), fetcher, state_path, NOW, dry_run=False)
    assert fetcher.urls and all(u.startswith(BASE_URL + "/") for u in fetcher.urls)


def test_unparseable_ticket_article_gets_check_this_and_dismiss_holds(state_path):
    table = pages()
    url = ART + "newcastle-united-sold-out-ticket-exchange-now-open"
    table[url] = table[url].replace("at the Amex", "away")
    cal = FakeCalendar()
    run_check(cal, Fetcher(table), state_path, NOW, dry_run=False)
    check_keys = [n.key for n in cal.events.values() if n.key.startswith("check:")]
    assert len(check_keys) == 1
    st = load(state_path)
    st.dismissed.add(check_keys[0])
    save(st, state_path)
    run_check(cal, Fetcher(table), state_path, NOW.replace(hour=22), dry_run=False)
    assert not any(n.key.startswith("check:") for n in cal.events.values())


def test_added_url_is_fetched(state_path):
    st = load(state_path)
    extra = ART + "bournemouth-and-nottingham-forest-ticket-information"
    st.articles[extra] = {"title": "added by hand", "published": "2026-10-23", "matches": []}
    save(st, state_path)
    table = pages()
    table[extra] = page("article-bournemouth-and-nottingham-forest-ticket-information.html.gz")
    cal = FakeCalendar()
    run_check(cal, Fetcher(table), state_path, NOW, dry_run=False)
    assert any(n.title == "Nottingham Forest v Albion" for n in cal.events.values())


def test_snapshot_of_article_text_written_on_real_run(state_path):
    run_check(FakeCalendar(), Fetcher(pages()), state_path, NOW, dry_run=False)
    snaps = list((state_path.parent / "snapshots").glob("*.txt"))
    assert any(s.read_text().startswith("Fulham v Albion") for s in snaps)
    assert all(len(s.read_text()) < 50_000 for s in snaps)  # the article, not the whole page


def test_points_reminder_arrives_10_days_after_the_match(state_path):
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    later = datetime(2027, 1, 5, 9, 0, tzinfo=TZ)  # Fulham away is Sat 26 Dec
    run_check(cal, Fetcher(pages()), state_path, later, dry_run=False)
    points = [n for n in cal.events.values() if n.key.startswith("points:")]
    assert [n.title.split(" (")[0] for n in points] == ["Points for Fulham"]
    assert points[0].start == later
    again = list(cal.calls)
    run_check(cal, Fetcher(pages()), state_path, later.replace(hour=11), dry_run=False)
    assert cal.calls == again  # once only


def test_home_league_article_is_read_once_then_left_alone(state_path):
    newcastle = ART + "newcastle-united-sold-out-ticket-exchange-now-open"
    f1 = Fetcher(pages())
    run_check(FakeCalendar(), f1, state_path, NOW, dry_run=False)
    assert newcastle in f1.urls
    f2 = Fetcher(pages())
    run_check(FakeCalendar(), f2, state_path, NOW.replace(hour=22), dry_run=False)
    assert newcastle not in f2.urls


def test_unreadable_article_is_listed_as_needing_a_look(state_path):
    st = load(state_path)
    st.articles[ART + "broken"] = {"title": "Leeds ticket information", "published": "2026-11-12", "matches": []}
    save(st, state_path)
    table = pages()
    table[ART + "broken"] = "<html>nothing here</html>"
    report = run_check(FakeCalendar(), Fetcher(table), state_path, NOW, dry_run=True)
    assert report.needs_look == ["Leeds ticket information"]
