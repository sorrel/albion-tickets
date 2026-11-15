import gzip
from datetime import date, datetime
from pathlib import Path


from albion_tickets.config import TZ
from albion_tickets.parse_article import article_text, is_tracked, parse_article

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 13)


def load(slug):
    return gzip.open(FIX / f"article-{slug}.html.gz", "rt").read()


def parsed(slug):
    url = f"https://www.brightonandhovealbion.com/media-article/{slug}"
    return parse_article(load(slug), url, TODAY)


def by_opponent(article, name):
    return next(m for m in article.matches if m.opponent == name)


def test_article_text_is_only_this_articles_body():
    text = article_text(load("fulham-ticket-information"), "fulham-ticket-information")
    assert text.startswith("Fulham v Albion")
    assert "Loan Management" not in text  # a related article elsewhere on the page


def test_fulham():
    a = parsed("fulham-ticket-information")
    assert a.published == date(2026, 11, 5)
    m = by_opponent(a, "Fulham")
    assert (m.home, m.competition) == (False, "Premier League")
    assert m.kickoff == datetime(2026, 12, 26, 15, 0, tzinfo=TZ)
    assert m.kickoff_confirmed
    assert [s.min_points for s in m.stages] == [300, 239, 208, None, None]
    assert m.stages[3].opens == datetime(2026, 11, 13, 9, 0, tzinfo=TZ)
    assert m.fixture_points == 5
    assert m.key == "2026-27-fulham-a-premier-league"
    assert m.unreadable == []


def test_two_matches_in_one_article():
    a = parsed("bournemouth-and-nottingham-forest-ticket-information")
    names = {m.opponent for m in a.matches}
    assert {"Bournemouth", "Nottingham Forest"} <= names
    forest = by_opponent(a, "Nottingham Forest")
    assert forest.home is False
    assert forest.kickoff == datetime(2026, 12, 5, 17, 30, tzinfo=TZ)
    assert [s.min_points for s in forest.stages[:4]] == [284, 225, 205, None]
    assert forest.fixture_points == 10
    bournemouth = by_opponent(a, "Bournemouth")
    assert bournemouth.kickoff == datetime(2026, 12, 2, 20, 15, tzinfo=TZ)
    assert bournemouth.stages[0].min_points == 342
    assert bournemouth.fixture_points == 5


def test_spurs():
    a = parsed("tottenham-hotspur-ticket-information")
    m = by_opponent(a, "Tottenham Hotspur")
    assert m.kickoff == datetime(2026, 12, 29, 19, 30, tzinfo=TZ)
    assert m.stages[1].min_points == 239


def test_home_premier_league_sold_out_news_is_ignorable():
    a = parsed("newcastle-united-sold-out-ticket-exchange-now-open")
    assert a.matches == []
    assert a.ignorable


def _m(**kw):
    from albion_tickets.model import Match, Status
    base = dict(key="k", opponent="X", home=False, competition="Premier League", kickoff=None,
                kickoff_confirmed=True, stages=[], status=Status(), fixture_points=None, url="u")
    base.update(kw)
    return Match(**base)


def test_premier_league_home_not_tracked():
    assert not is_tracked(_m(home=True))


def test_home_cup_tie_tracked():
    assert is_tracked(_m(home=True, competition="UEFA Conference League"))


def test_away_tracked():
    assert is_tracked(_m())


def test_unconfirmed_kickoff():
    from albion_tickets.parse_article import parse_text
    text = ("Leeds v Albion\nSaturday 13 March - kick-off 3pm\nPlease note: Fixture date and time is not yet confirmed.\n"
            "On sale dates:\nAll STHs/1901 Club members: Tue 2 Feb")
    (m,) = parse_text(text, "u", "Leeds ticket information", date(2027, 1, 20)).matches
    assert not m.kickoff_confirmed


def test_key_ignores_kickoff():
    from albion_tickets.parse_article import parse_text
    t1 = "Leeds v Albion\nSaturday 13 March - kick-off 3pm\nAll STHs/1901 Club members: Tue 2 Feb"
    t2 = "Leeds v Albion\nSunday 14 March - kick-off 2pm\nAll STHs/1901 Club members: Tue 2 Feb"
    k1 = parse_text(t1, "u", "t", date(2027, 1, 20)).matches[0].key
    k2 = parse_text(t2, "u", "t", date(2027, 1, 20)).matches[0].key
    assert k1 == k2 == "2026-27-leeds-a-premier-league"


def test_home_cup_tie_from_text():
    from albion_tickets.parse_article import parse_text
    text = ("Brighton & Hove Albion v AS Monaco\nThursday 10 December - kick-off 8pm\n"
            "UEFA Conference League: League Phase\nSeason Ticket Holders: Mon 16 Nov 9am")
    (m,) = parse_text(text, "u", "Monaco ticket information", date(2026, 11, 10)).matches
    assert m.home and m.opponent == "AS Monaco" and m.competition == "UEFA Conference League"


def test_match_colon_layout_selling_only_to_members_and_guests_is_a_home_league_game():
    a = parsed("manchester-united-ticket-information")
    assert a.matches == [] and a.ignorable


def test_match_colon_layout_with_a_season_ticket_stage_is_not_ignored():
    text = ("Match: Fulham\nDate: Saturday 2 January, kick-off 12:30pm.\nOn sale dates:\n"
            "STHs/1901 Club Members w/ 200+ Points: 9am, Tuesday 10 Nov\n")
    from albion_tickets.parse_article import parse_text
    a = parse_text(text, "https://u", "Fulham ticket information", date(2026, 11, 1))
    assert not a.ignorable
