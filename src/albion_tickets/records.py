"""A match, from any source, → its record in the state and its calendar notices.

Shared by the news check (run.py) and saved-page imports (importing.py).
"""
from dataclasses import replace
from datetime import date, datetime, timedelta

from . import news_updates, venues
from .model import Match, Status
from .notices import Notice, change_notices, fixture, notices_for, points_due
from .rules import decide
from .store import Change, MatchRecord, State, observe
from .sync import Report

KEEP_TRACKING = timedelta(days=1)  # a match's events are kept until the day after it
KEEP_WITH_TICKETS = {"fixture", "kickoff_moved"}  # with a ticket in hand, sale news is noise
FROM_PAGE = ("import", "draw")  # sources no article owns: none ever retires their events
SEASON_TICKET = "season_ticket"  # the kind of a home league game: in the calendar, but no sale reminders


def season_ticket(m: Match) -> bool:
    """A home league game: the season ticket covers it."""
    return m.home and m.competition == "Premier League"


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def from_page(rec: MatchRecord) -> bool:
    return rec.summary.get("source") in FROM_PAGE


def match_notices(state: State, m: Match, now: datetime, report: Report,
                  published: date | None = None) -> list[Notice]:
    """Record a match read from a ticket article or saved page (published on `published`); its notices."""
    rec = state.matches.get(m.key)
    m = news_updates.with_news(m, rec, published)
    if rec and rec.summary.get("source") == "draw":
        rec.kickoffs.clear()  # the draw's provisional date: the real one is not a "move"
    # Decide once to record what's new, then again with the record's first-seen times.
    provisional = decide(m, state.points, now, _dt(rec.first_sold_out_seen) if rec else None)
    changes = observe(state, m, provisional.opens, now)
    rec = state.matches[m.key]
    outcome = decide(m, state.points, now, _dt(rec.first_sold_out_seen))
    if outcome.opens is not None and outcome.opens != provisional.opens:
        rec.stage_opens = {"value": outcome.opens.isoformat(), "seen": now.isoformat()}
    rec.first_problem = (rec.first_problem or now.isoformat()) if outcome.kind == "unreadable" else None
    rec.summary = summary(m, outcome.kind, outcome.opens, outcome.sold_out_stage,
                          outcome.stage.label if outcome.stage else None)
    report.changes.extend(described(changes, m))
    out = [*notices_for(m, outcome, state.points, now, _dt(rec.stage_opens.get("seen")),
                        _dt(rec.first_sold_out_seen), _dt(rec.first_problem)),
           *change_notices(changes, m, now)]
    if m.key in state.have_tickets:
        out = [n for n in out if n.key.split(":", 1)[0] in KEEP_WITH_TICKETS]
    return located(out, state, m)


def fixture_only(state: State, m: Match, now: datetime, report: Report) -> list[Notice]:
    """Record a saved-page match whose sales don't concern the user: its fixture alone.

    A home league game (the season ticket covers it), or a match with no sale
    dates on the page (sold out, on sale now, or none yet).
    """
    changes = observe(state, m, None, now)
    if season_ticket(m):
        kind, sold_out = SEASON_TICKET, None
    else:
        kind, sold_out = "sold_out" if m.status.sold else "on_sale" if m.on_sale_now else "no_dates", m.status.sold_out_to
    state.matches[m.key].summary = summary(m, kind, None, sold_out, None) | {"source": "import"}
    report.changes.extend(described(changes, m))
    return located(fixture(m), state, m) + change_notices(changes, m, now)


def summary(m: Match, kind: str, opens: datetime | None, sold_out_stage: str | None,
            your_stage: str | None) -> dict:
    """What the record keeps of the latest reading: rebuilt every time the match is read."""
    return {"opponent": m.opponent, "home": m.home, "competition": m.competition, "url": m.url,
            "kind": kind, "opens": opens.isoformat() if opens else None, "sold_out_stage": sold_out_stage,
            "kickoff_confirmed": m.kickoff_confirmed, "worth": m.fixture_points, "your_stage": your_stage,
            "stages": [{"label": st.label, "opens": st.opens.isoformat(), "min_points": st.min_points,
                        "pending": st.brackets_pending} for st in m.stages]}


def described(changes: list[Change], m: Match) -> list[str]:
    """'Fulham: kickoff moved <old> → <new>' for the run's summary."""
    return [f"{m.opponent}: {c.kind.replace('_', ' ')} {c.old} → {c.new}" for c in changes]


def located(notices: list[Notice], state: State, m: Match) -> list[Notice]:
    """Give the fixture event its ground."""
    rec = state.matches.get(m.key)
    where = venues.location(m.opponent, m.home, m.venue or (rec.venue if rec else None), state.venues)
    if where is None:
        return notices
    geo = (where.lat, where.lon) if where.lat is not None else None
    return [replace(n, location=where.address, geo=geo) if n.key.startswith("fixture:") else n for n in notices]


def as_match(key: str, rec: MatchRecord) -> Match:
    """A record back as a match (no sale stages), with the latest Fixture News applied."""
    s = rec.summary
    m = Match(key, rec.opponent, rec.home, s.get("competition", ""), rec.kickoff, s.get("kickoff_confirmed", True),
              [], Status(), s.get("worth"), s.get("url", ""), venue=rec.venue,
              date_confirmed=s.get("date_confirmed", True))
    return news_updates.with_news(m, rec, None)


def refresh_fixtures(state: State, notices: list[Notice], owners_ok: set[str], now: datetime) -> list[Notice]:
    """Fixture events this run didn't produce, rebuilt from their records.

    So a change in how events look reaches every match: imported ones, and
    those whose articles are no longer read. From the club's news only events
    that exist are refreshed, so one an article retired is never brought back;
    a saved-page match is never retired, so its event is also written if an
    earlier attempt failed. A match an article read this run (owners_ok) is
    left to that article, including dropping it.
    """
    produced = {n.key for n in notices}
    out: list[Notice] = []
    for key, rec in state.matches.items():
        if f"fixture:{key}" in produced or key in owners_ok or rec.kickoff is None:
            continue
        if f"fixture:{key}" not in state.events and not from_page(rec):
            continue
        if rec.kickoff + KEEP_TRACKING >= now:
            m = as_match(key, rec)
            out.extend(located(fixture(m), state, m))
    return out


def points_reminders(state: State, now: datetime) -> list[Notice]:
    """'Update your points' for away matches whose points should have landed."""
    due = (points_due(key, rec.opponent, rec.kickoff, rec.summary.get("worth"), now)
           for key, rec in state.matches.items() if not rec.summary.get("home", True) and rec.kickoff)
    return [n for n in due if n is not None]


def same_fixture(state: State, m: Match) -> str | None:
    """The key of a recorded match on the same day, at the same end, as m."""
    if m.kickoff is None:
        return None
    return next((key for key, rec in state.matches.items()
                 if rec.kickoff and rec.home == m.home and rec.kickoff.date() == m.kickoff.date()), None)


def rename(state: State, old: str, new: str) -> None:
    """Move a record to a new key (names differ between sources), keeping its history and tickets."""
    state.matches[new] = state.matches.pop(old)
    if old in state.have_tickets:
        state.have_tickets.discard(old)
        state.have_tickets.add(new)


def adopt_import(state: State, m: Match, owners_ok: set[str]) -> None:
    """The club's article now covers a match first seen on a saved ticket page.

    Names differ between the two ("Spurs" / "Tottenham Hotspur"), so the match
    is found by its day. Its record moves to the article's key, and the
    import's events are retired: the article's notices replace them this run.
    """
    if m.key in state.matches:
        return
    old = same_fixture(state, m)
    if old is not None and state.matches[old].summary.get("source") == "import":
        rename(state, old, m.key)
        owners_ok.add(old)
