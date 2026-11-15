"""Fixture News: moved kick-offs, postponements and cup draws, end to end."""
import functools
import gzip
from datetime import date, datetime
from pathlib import Path

import pytest

from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.config import BASE_URL, TZ
from albion_tickets.fetch import FetchResult
from albion_tickets.fixture_news import read
from albion_tickets.parse_article import article_text
from albion_tickets.run import run_check
from albion_tickets.store import MatchRecord, State, load, save

FIX = Path(__file__).parent / "fixtures"
ART = BASE_URL + "/media-article/"
NOV = "mft-fixture-news-brentford-hull-city-newcastle-united-november-selection-september-2026"
DRAW = "mft-fixture-news-emirates-fa-cup-manchester-united-third-round-december-2025"
CHANGED = "chelsea-and-coventry-city-fixture-dates-changed"


@functools.cache
def real(name: str) -> str:
    return gzip.open(FIX / f"article-{name}.html.gz", "rt").read()


def article(slug: str, title: str, published: str, *paragraphs: str) -> str:
    """A page in the club's payload format, as the trimmed fixtures are."""
    nodes = ",".join(f'{{nodeType:"paragraph",data:{{}},content:[{{nodeType:"text",value:"{p}",marks:[],data:{{}}}}]}}'
                     for p in paragraphs)
    return (f'<script>a.name="{title}";a.slug="{slug}";a.mediaType="Article";a.publishDateTime="{published}";'
            f'a.categories=[{{name:"Fixture News"}}];a.articleBody={{body:{{nodeType:"document",data:{{}},'
            f'content:[{nodes}]}}}};</script>')


def listing(*items: tuple[str, str, str]) -> str:
    """The all-news listing holding these (slug, title, published) Fixture News items."""
    return "".join(f'<script>b{i}.name="{t}";b{i}.slug="{s}";b{i}.mediaType="Article";'
                   f'b{i}.publishDateTime="{p}";b{i}.categories=[{{name:"Fixture News"}}];</script>'
                   for i, (s, t, p) in enumerate(items))


class Fetcher:
    def __init__(self, table):
        self.table, self.urls = table, []

    def __call__(self, url):
        self.urls.append(url)
        body = self.table.get(url)
        return FetchResult(200, body, url, None) if body else FetchResult(404, "", url, "HTTPError 404")


def pages(*articles: tuple[str, str, str, str]) -> dict[str, str]:
    """A listing plus each (slug, title, published, html) article."""
    return {BASE_URL + "/all-latest-news": listing(*[(s, t, p) for s, t, p, _ in articles]),
            **{ART + s: html for s, _, _, html in articles}}


def tracked(path: Path, *matches: tuple[str, str, bool, str, str]) -> None:
    """Save a state tracking (key, opponent, home, competition, kick-off) matches, each with a fixture event."""
    s = load(path)
    for key, opponent, home, competition, kickoff in matches:
        s.matches[key] = MatchRecord(kickoffs=[(kickoff, "2026-09-01T00:00:00+00:00")], summary={
            "opponent": opponent, "home": home, "competition": competition, "url": "saved page", "source": "import"})
        s.events[f"fixture:{key}"] = {"uid": key, "owner": key, "one_shot": False, "fp": "old",
                                      "start": kickoff, "title": "x"}
    save(s, path)


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    return p


def fixtures(cal):
    return {n.key: n for n in cal.events.values() if n.key.startswith("fixture:")}


HULL = ("2026-27-hull-city-a-premier-league", "Hull City", False, "Premier League", "2026-11-21T15:00:00+00:00")
FULHAM = ("2026-27-fulham-a-premier-league", "Fulham", False, "Premier League", "2026-12-26T15:00:00+00:00")
NOV_PAGE = (NOV, "Three Premier League matches in November moved for TV", "2026-09-21T15:00+01:00", real("fixture-news-nov"))


# --- reading ----------------------------------------------------------------

def test_reads_the_real_articles():
    nov = read(article_text(real("fixture-news-nov"), NOV), "", date(2026, 9, 21),
               ["Hull City", "Brentford", "Newcastle United"])
    assert [(m.opponent, m.side, m.when, m.postponed) for m in nov.moves] == [
        ("Brentford", "home", datetime(2026, 11, 8, 14, tzinfo=TZ), False),
        ("Hull City", "away", datetime(2026, 11, 22, 14, tzinfo=TZ), False),
        ("Newcastle United", "home", datetime(2026, 11, 29, 14, 5, tzinfo=TZ), False)]
    changed = read(article_text(real("fixture-dates-changed"), CHANGED), "", date(2026, 7, 7), ["Chelsea"])
    assert [(m.side, m.when) for m in changed.moves] == [("away", datetime(2026, 8, 30, 14, tzinfo=TZ))]
    [tie] = read(article_text(real("fa-cup-draw"), DRAW), "Albion draw Manchester United away", date(2025, 12, 8),
                 []).draws
    assert (tie.opponent, tie.home, tie.competition, tie.date_confirmed) == ("Manchester United", False, "FA Cup", False)
    assert tie.kickoff == datetime(2026, 1, 10, 15, tzinfo=TZ)


def test_postponed_names_the_old_date_and_new_date_wording_is_a_move():
    text = ("Our Premier League game at Fulham on Saturday 26 December has been postponed.\n"
            "Our game at Fulham will now take place on Wednesday 3 February, kick-off 7.30pm.")
    off, on = read(text, "", date(2026, 12, 20), ["Fulham"]).moves
    assert off.postponed and off.when.date() == date(2026, 12, 26)
    assert not on.postponed and on.when == datetime(2027, 2, 3, 19, 30, tzinfo=TZ)


def test_two_legged_tie():
    text = ("Albion have been drawn against AS Roma in the Conference League round of 16.\n"
            "Brighton & Hove Albion v AS Roma\n"
            "The first leg is away at the Stadio Olimpico on Thursday 11 March, kick-off 5.45pm UK time.\n"
            "The second leg is at home at the Amex on Thursday 18 March, kick-off 8pm.")
    legs = read(text, "Albion draw Roma", date(2027, 2, 26), []).draws
    assert [(t.home, t.kickoff) for t in legs] == [(False, datetime(2027, 3, 11, 17, 45, tzinfo=TZ)),
                                                    (True, datetime(2027, 3, 18, 20, tzinfo=TZ))]


# --- end to end ---------------------------------------------------------------

def test_a_tv_move_updates_the_match_and_alerts_once(state_path):
    tracked(state_path, HULL)
    cal = FakeCalendar()
    now = datetime(2026, 9, 22, 9, tzinfo=TZ)
    report = run_check(cal, Fetcher(pages(NOV_PAGE)), state_path, now, dry_run=False)
    hull = fixtures(cal)["fixture:2026-27-hull-city-a-premier-league"]
    assert hull.start == datetime(2026, 11, 22, 14, tzinfo=TZ) and hull.title == "⚽ Hull City v Albion"
    assert any(n.key.startswith("kickoff_moved:2026-27-hull-city") for n in cal.events.values())
    assert any("Hull City: kick-off moved" in c for c in report.changes)
    assert not any("Brentford" in c or "Newcastle" in c for c in report.changes)  # home league: not tracked
    again = run_check(cal, Fetcher(pages(NOV_PAGE)), state_path, datetime(2026, 9, 23, 9, tzinfo=TZ), False)
    assert (again.changes, again.created, again.updated) == ([], [], [])


def test_news_is_read_about_daily(state_path):
    fetch = Fetcher(pages(NOV_PAGE))
    run_check(FakeCalendar(), fetch, state_path, datetime(2026, 9, 22, 9, tzinfo=TZ), dry_run=False)
    run_check(FakeCalendar(), fetch, state_path, datetime(2026, 9, 22, 11, tzinfo=TZ), dry_run=False)
    run_check(FakeCalendar(), fetch, state_path, datetime(2026, 9, 23, 9, tzinfo=TZ), dry_run=False)
    assert fetch.urls.count(ART + NOV) == 2


def test_postponed_then_rearranged(state_path):
    tracked(state_path, FULHAM)
    cal = FakeCalendar()
    off = ("fulham-postponed", "Fulham game postponed", "2026-12-20T10:00+00:00",
           article("fulham-postponed", "Fulham game postponed", "2026-12-20T10:00+00:00",
                   "Our Premier League game at Fulham on Saturday 26 December has been postponed due to a frozen pitch."))
    run_check(cal, Fetcher(pages(off)), state_path, datetime(2026, 12, 20, 11, tzinfo=TZ), dry_run=False)
    assert fixtures(cal)["fixture:2026-27-fulham-a-premier-league"].title == "⚽ Fulham v Albion (postponed)"
    assert any(n.title == "⚠️ Fulham v Albion postponed" for n in cal.events.values())
    on = ("fulham-new-date", "New date for Fulham", "2027-01-05T10:00+00:00",
          article("fulham-new-date", "New date for Fulham", "2027-01-05T10:00+00:00",
                  "Our game away at Fulham, postponed in December, will now take place on Wednesday 3 February, "
                  "kick-off 7.30pm."))
    run_check(cal, Fetcher(pages(on)), state_path, datetime(2027, 1, 5, 11, tzinfo=TZ), dry_run=False)
    fulham = fixtures(cal)["fixture:2026-27-fulham-a-premier-league"]
    assert fulham.title == "⚽ Fulham v Albion" and fulham.start == datetime(2027, 2, 3, 19, 30, tzinfo=TZ)


def test_a_cup_draw_adds_the_tie(state_path):
    cal = FakeCalendar()
    draw = (DRAW, "Albion draw Manchester United away in FA Cup third round", "2025-12-08T19:00+00:00",
            real("fa-cup-draw"))
    report = run_check(cal, Fetcher(pages(draw)), state_path, datetime(2025, 12, 9, 9, tzinfo=TZ), dry_run=False)
    tie = fixtures(cal)["fixture:2025-26-manchester-united-a-fa-cup"]
    assert tie.title == "⚽ Manchester United v Albion (date not confirmed)"
    assert tie.start == datetime(2026, 1, 10, 15, tzinfo=TZ) and tie.location.startswith("Old Trafford")
    assert any(n.title.startswith("⚠️ New FA Cup tie: Manchester United v Albion") for n in cal.events.values())
    assert any(c.startswith("New FA Cup tie") for c in report.changes)


def test_an_unclear_sentence_asks_rather_than_guesses(state_path):
    tracked(state_path, FULHAM)
    cal = FakeCalendar()
    vague = ("fulham-vague", "Fixture update", "2026-11-10T10:00+00:00",
             article("fulham-vague", "Fixture update", "2026-11-10T10:00+00:00",
                     "The Fulham game will now be played on Sunday 14 February, kick-off 2pm."))
    run_check(cal, Fetcher(pages(vague)), state_path, datetime(2026, 11, 10, 11, tzinfo=TZ), dry_run=False)
    assert fixtures(cal)["fixture:2026-27-fulham-a-premier-league"].start.date() == date(2026, 12, 26)
    assert any(n.key == "check:fulham-vague" for n in cal.events.values())


def test_upcoming_shows_postponed_and_provisional_dates(state_path):
    from click.testing import CliRunner
    from albion_tickets import cli
    tracked(state_path, (FULHAM[0], "Fulham", False, "Premier League", "2000-12-26T15:00:00+00:00"))
    s = load(state_path)
    s.matches[FULHAM[0]].news = {"postponed": "yes", "published": "2000-12-20", "url": "u"}  # old date long gone
    s.matches["2026-27-wrexham-a-fa-cup"] = MatchRecord(kickoffs=[("2099-01-09T15:00:00+00:00", "x")], summary={
        "opponent": "Wrexham", "home": False, "competition": "FA Cup", "kind": "no_dates", "source": "draw",
        "kickoff_confirmed": False, "date_confirmed": False})
    save(s, state_path)
    out = CliRunner().invoke(cli.cli, ["upcoming"]).output
    assert next(l for l in out.splitlines() if l.startswith("Wrexham (A)")).rstrip().endswith("15:00?")
    assert "postponed" in next(l for l in out.splitlines() if l.startswith("Fulham (A)"))
