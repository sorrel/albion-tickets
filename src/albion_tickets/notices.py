"""What goes in the calendar.

Every time here is anchored to when the tool first *saw* something, never to
the current run, so re-running every two hours produces identical notices and
never re-fires an alert.
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from .dates import at_london
from .model import Match
from .rules import Outcome
from .store import Change

SOON = timedelta(minutes=5)
NOW_ALARM = timedelta(minutes=2)


@dataclass(frozen=True)
class Notice:
    key: str
    title: str
    start: datetime
    end: datetime
    alarms: list[datetime] = field(default_factory=list)
    notes: str = ""
    one_shot: bool = False
    why: str = ""  # for "check this": what the tool couldn't make sense of
    location: str = ""  # fixture events: the ground's address
    geo: tuple[float, float] | None = None  # and its map pin, when known


def _when(dt: datetime) -> str:
    """'Fri 4 Dec 9am', 'Sat 16 Jan 3pm', 'Tue 29 Dec 7.30pm'."""
    hour = dt.hour % 12 or 12
    mins = f".{dt.minute:02d}" if dt.minute else ""
    return f"{dt:%a} {dt.day} {dt:%b} {hour}{mins}{'am' if dt.hour < 12 else 'pm'}"


def match_name(opponent: str, home: bool) -> str:
    return f"Albion v {opponent}" if home else f"{opponent} v Albion"


def fixture_name(m: Match) -> str:
    return match_name(m.opponent, m.home)


def _where(m: Match) -> str:
    return "away" if not m.home else m.competition


def _sale_alarms(opens: datetime, seen: datetime) -> list[datetime]:
    if opens <= seen:  # already over when first found: nothing to warn about
        return []
    wanted = [
        at_london(opens.date() - timedelta(days=1), time(19, 0)),
        opens.replace(hour=8, minute=30),
        opens.replace(hour=8, minute=55),
    ]
    wanted = [a for a in wanted if seen <= a < opens]
    return wanted or [seen + NOW_ALARM]


def _notes(m: Match, o: Outcome) -> str:
    lines = [f"{s.label}: {_when(s.opens)}" for s in m.stages]
    if o.pattern_note:
        lines.append(o.pattern_note)
    if o.stage is not None and o.stage.time_assumed:
        lines.append("time assumed 9am (the article gives no time)")
    lines.append(m.url)
    return "\n".join(lines)


POINTS_LAND_AFTER = timedelta(days=10)  # the club credits loyalty points about 10 days after a match


def notices_for(m: Match, o: Outcome, points: int, now: datetime,
                sale_seen: datetime | None, sold_out_seen: datetime | None,
                problem_seen: datetime | None = None) -> list[Notice]:
    out: list[Notice] = []
    notes = _notes(m, o)
    seen = sale_seen or now

    over_when_found = o.opens is not None and o.opens <= seen  # nothing to remind about
    if o.kind in ("sale", "predicted_sale", "sold_out_before_you") and over_when_found:
        pass
    elif o.kind in ("sale", "predicted_sale") and o.opens is not None:
        title = (f"🎟️ {m.opponent} {_where(m)}: your sale {_when(o.opens).rsplit(' ', 1)[0]} "
                 f"{_when(o.opens).rsplit(' ', 1)[1]} ({o.stage.label}, you have {points})")
        if o.kind == "predicted_sale":
            title += " (predicted: brackets not announced yet)"
        out.append(Notice(f"sale:{m.key}", title, o.opens, o.opens + timedelta(minutes=15),
                          _sale_alarms(o.opens, seen), notes))
    elif o.kind == "sold_out_before_you" and o.opens is not None:
        out.append(Notice(f"sale:{m.key}", f"{m.opponent} sold out at {o.sold_out_stage} (you have {points})",
                          o.opens, o.opens + timedelta(minutes=15), [], notes))
    elif o.kind == "exchange_open":
        start = (sold_out_seen or now) + SOON
        out.append(Notice(f"exchange:{m.key}",
                          f"🎟️ {m.opponent} {_where(m)}: ticket exchange open to you (sold out at {o.sold_out_stage})",
                          start, start + timedelta(minutes=15), [start], notes))
        closes = m.status.exchange_closes
        if closes is not None:
            eve = at_london(closes.date() - timedelta(days=1), time(19, 0))
            out.append(Notice(f"exchange_closing:{m.key}",
                              f"🎟️ {m.opponent} exchange closes {_when(closes)}",
                              eve, eve + timedelta(minutes=15), [eve], notes))
    elif o.kind == "unreadable":
        first = problem_seen or now
        reason = f"couldn't read a sale line: “{m.unreadable[0]}”" if m.unreadable else "found no sale dates in it"
        out.append(check_this(f"check:{m.key}", m.url, f"{fixture_name(m)} tickets", first,
                              first if o.urgent else None, reason))

    if m.kickoff is not None:
        out.append(Notice(f"fixture:{m.key}", f"⚽ {fixture_name(m)}{fixture_suffix(m)}",
                          m.kickoff, m.kickoff + timedelta(hours=2), [], m.url))
    return out


POINTS_STALE_AFTER = timedelta(days=14)  # a first run long after: don't nag about old matches


def points_due(key: str, opponent: str, kickoff: datetime, worth: int | None,
               now: datetime) -> Notice | None:
    """'Update your points' once the club has credited them: never before."""
    landed = at_london(kickoff.date() + POINTS_LAND_AFTER, time(9, 0))
    if now < landed or now > landed + POINTS_STALE_AFTER:
        return None
    start = landed if now - landed < SOON else now + SOON
    title = (f"Points for {opponent} ({kickoff.day} {kickoff:%b}) should be on your account: "
             f"if you went (worth {worth if worth is not None else '?'}), run albion points <n>")
    return Notice(f"points:{key}", title, start, start + timedelta(minutes=15), [start], "", one_shot=True)


def alert(key: str, title: str, notes: str, now: datetime) -> Notice:
    """A one-off "this changed" alert, five minutes from now."""
    start = now + SOON
    return Notice(key, f"⚠️ {title}", start, start + timedelta(minutes=15), [start], notes, one_shot=True)


def moved(kind: str, key: str, opponent: str, old: str, new: str, url: str, now: datetime) -> Notice:
    """'⚠️ Fulham: kick-off moved Sat 26 Dec 3pm → Sun 27 Dec 2pm' (kind: kickoff_moved or sale_moved)."""
    what = "kick-off moved" if kind == "kickoff_moved" else "sale moved"
    old_s, new_s = _when(datetime.fromisoformat(old)), _when(datetime.fromisoformat(new))
    return alert(f"{kind}:{key}:{new}", f"{opponent}: {what} {old_s} → {new_s}", url, now)


def change_notices(changes: list[Change], matches: dict[str, Match], now: datetime) -> list[Notice]:
    return [moved(c.kind, c.match_key, matches[c.match_key].opponent, c.old, c.new, matches[c.match_key].url, now)
            for c in changes]


def fixture_suffix(m: Match) -> str:
    """What a fixture's title says about its date: postponed, or not yet fixed."""
    if m.postponed:
        return " (postponed)"
    if not m.date_confirmed:
        return " (date not confirmed)"
    return "" if m.kickoff_confirmed else " (time not confirmed)"


def check_this(key: str, url: str, title: str, first_seen: datetime, soonest: datetime | None,
               reason: str = "") -> Notice:
    start = at_london(first_seen.date() + timedelta(days=1), time(8, 30))
    if soonest is not None and soonest < start:
        start = first_seen + SOON
    notes = f"{reason}\n{url}" if reason else url
    return Notice(key, f"Check this ticket article: {title}", start, start + timedelta(minutes=15), [start],
                  notes, why=reason)
