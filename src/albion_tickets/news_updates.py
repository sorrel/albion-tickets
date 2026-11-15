"""Fixture News applied to tracked matches: moved kick-offs, postponements, new cup ties.

`fixture_news` reads an article's sentences; this decides which tracked match
each one means and records it on that match (`MatchRecord.news`). The fixture
event itself is rebuilt from the record by `run._refresh_fixtures`, or by the
match's ticket article through `with_news`, so every source agrees.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta

from . import fixture_news
from .dates import at_london
from .fixture_news import Draw, Move
from .model import Match
from .notices import Notice, alert, check_this, match_name, moved
from .parse_article import _season, _slug
from .store import MatchRecord, State

REREAD_AFTER = timedelta(hours=20)  # about daily while the article is in the listing
KEEP_READING = timedelta(days=7)  # the listing's own window
NEAR = timedelta(days=21)  # how close a match must be when the article doesn't say home or away


def due(info: dict, now: datetime) -> bool:
    """Whether a Fixture News article should be read in this run."""
    if now.date() - date.fromisoformat(info["published"]) > KEEP_READING:
        return False
    last = info.get("read")
    return last is None or now - datetime.fromisoformat(last) >= REREAD_AFTER


def with_news(m: Match, rec: MatchRecord | None, published: date | None) -> Match:
    """The match as the latest Fixture News has it, if that is newer than m's source."""
    news = rec.news if rec else {}
    if not news or (published and news["published"] < published.isoformat()):
        return m
    if news.get("postponed"):
        return replace(m, postponed=True)
    return replace(m, kickoff=datetime.fromisoformat(news["kickoff"]), kickoff_confirmed=bool(news.get("confirmed")),
                   postponed=False)


def apply(state: State, url: str, info: dict, text: str, now: datetime, changes: list[str]) -> list[Notice]:
    """Record what one article says; returns its alerts (and a "check this" if unsure)."""
    published = date.fromisoformat(info["published"])
    tracked = {k: r for k, r in state.matches.items() if _upcoming(r, now)}
    known = sorted({r.summary["opponent"] for r in tracked.values() if r.summary.get("opponent")})
    news = fixture_news.read(text, info.get("title", ""), published, known)
    out: list[Notice] = []
    unsure = list(news.unclear)
    for mv in news.moves:
        key = _match_for(mv, tracked)
        if key is not None:
            out.extend(_record_move(state.matches[key], key, mv, published, url, now, changes))
        elif mv.side is None:  # a tracked club, but which match? ask rather than guess
            unsure.append(mv.sentence)
    for tie in news.draws:
        out.extend(_add_tie(state, tie, published, url, now, changes))
    if unsure:
        first = datetime.fromisoformat(info.setdefault("first_problem", now.isoformat()))
        out.append(check_this(f"check:{url.rsplit('/', 1)[-1]}", url, info.get("title", url), first, None,
                              f"couldn't tell which match: “{unsure[0][:80]}”"))
    info["read"] = now.isoformat()
    return out


def _kickoff(rec: MatchRecord) -> datetime:
    return datetime.fromisoformat(rec.kickoffs[-1][0])


def _upcoming(rec: MatchRecord, now: datetime) -> bool:
    """Still to be played, or postponed and awaiting its new date."""
    return bool(rec.kickoffs) and (_kickoff(rec) + timedelta(days=1) >= now or bool(rec.news.get("postponed")))


def _match_for(mv: Move, tracked: dict[str, MatchRecord]) -> str | None:
    """The tracked match a sentence means, or None.

    Same club, and the same end of the pitch when the sentence says which. One
    such match (or one already postponed, awaiting its new date) is it. Among
    several, or when home/away is unsaid, the one nearest the date given.
    """
    side_fits = lambda r: mv.side is None or r.summary.get("home") == (mv.side == "home")
    cands = {k: r for k, r in tracked.items() if r.summary.get("opponent") == mv.opponent and side_fits(r)}
    waiting = [k for k, r in cands.items() if r.news.get("postponed")]
    if waiting and not mv.postponed:
        return waiting[0]
    if len(cands) == 1 and mv.side is not None:
        return next(iter(cands))
    if mv.when is None:
        return min(cands, key=lambda k: _kickoff(cands[k]), default=None)
    near = {k: abs(_kickoff(r) - mv.when) for k, r in cands.items()}
    best = min(near, key=near.get, default=None)
    return best if best is not None and (mv.side is not None or near[best] <= NEAR) else None


def _record_move(rec: MatchRecord, key: str, mv: Move, published: date, url: str, now: datetime,
                 changes: list[str]) -> list[Notice]:
    """Record a postponement or a new kick-off; returns the alert, if it is news."""
    base = {"published": published.isoformat(), "url": url}
    opponent = rec.summary.get("opponent", key)
    if mv.postponed:
        if rec.news.get("postponed"):
            return []
        rec.news = {**base, "postponed": "yes"}
        changes.append(f"{opponent}: postponed")
        name = match_name(opponent, rec.summary.get("home", False))
        return [alert(f"postponed:{key}:{published}", f"{name} postponed", url, now)]
    old = rec.kickoffs[-1][0]
    new = mv.when if mv.time_given else at_london(mv.when.date(), _kickoff(rec).astimezone(mv.when.tzinfo).time())
    rec.news = {**base, "kickoff": new.isoformat(), "confirmed": "yes" if mv.time_given else ""}
    if new.isoformat() == old:
        return []
    rec.kickoffs.append((new.isoformat(), now.isoformat()))
    changes.append(f"{opponent}: kick-off moved {old} → {new.isoformat()}")
    return [moved("kickoff_moved", key, opponent, old, new.isoformat(), url, now)]


def _add_tie(state: State, tie: Draw, published: date, url: str, now: datetime, changes: list[str]) -> list[Notice]:
    """A new cup tie from a draw: a record (and so a fixture event) plus an alert."""
    on = tie.kickoff.date() if tie.kickoff else published
    key = f"{_season(on)}-{_slug(tie.opponent)}-{'h' if tie.home else 'a'}-{_slug(tie.competition)}"
    if key in state.matches:
        return []
    state.matches[key] = MatchRecord(
        kickoffs=[(tie.kickoff.isoformat(), now.isoformat())] if tie.kickoff else [],
        last_seen=now.isoformat(),
        summary={"opponent": tie.opponent, "home": tie.home, "competition": tie.competition, "url": url,
                 "kind": "no_dates", "opens": None, "source": "draw", "stages": [], "worth": None,
                 "kickoff_confirmed": tie.time_given, "date_confirmed": tie.date_confirmed})
    name, when = match_name(tie.opponent, tie.home), f"{tie.kickoff:%a %d %b}" if tie.kickoff else "date to come"
    changes.append(f"New {tie.competition} tie: {name}, {when}")
    return [alert(f"new_tie:{key}", f"New {tie.competition} tie: {name} ({when})", url, now)]
