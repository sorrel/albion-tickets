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

SOON = timedelta(minutes=5)  # an alert "now" lands a few minutes ahead, so the phone still rings
NOW_ALARM = timedelta(minutes=2)
REMINDER_LENGTH = timedelta(minutes=15)
POINTS_LAND_AFTER = timedelta(days=10)  # the club credits loyalty points about 10 days after a match
POINTS_STALE_AFTER = timedelta(days=14)  # a first run long after: don't nag about old matches
IMPORT_EVERY = timedelta(weeks=3)  # how often to save the ticket pages again
IMPORT_NAG = timedelta(weeks=1)  # then again each week until it's done
IMPORT_KEY = "import_due:ticket-pages"  # one event, moved along by each import


@dataclass(frozen=True)
class Notice:
    key: str  # "<kind>:<match key>[:…]"; the kind decides how the event is handled
    title: str
    start: datetime
    end: datetime
    alarms: list[datetime] = field(default_factory=list)
    notes: str = ""
    one_shot: bool = False  # written once and never updated or removed (alerts)
    why: str = ""  # for "check this": what the tool couldn't make sense of
    location: str = ""  # fixture events: the ground's address
    geo: tuple[float, float] | None = None  # and its map pin, when known


def reminder(key: str, title: str, start: datetime, notes: str = "", alarms: list[datetime] | None = None,
             **extra) -> Notice:
    """A short event that rings at its start (unless given other alarms)."""
    return Notice(key, title, start, start + REMINDER_LENGTH, [start] if alarms is None else alarms, notes,
                  **extra)


def spoken(dt: datetime) -> str:
    """'Fri 4 Dec 9am', 'Sat 16 Jan 3pm', 'Tue 29 Dec 7.30pm': how titles say a time."""
    hour = dt.hour % 12 or 12
    mins = f".{dt.minute:02d}" if dt.minute else ""
    return f"{dt:%a} {dt.day} {dt:%b} {hour}{mins}{'am' if dt.hour < 12 else 'pm'}"


def match_name(opponent: str, home: bool) -> str:
    return f"Albion v {opponent}" if home else f"{opponent} v Albion"


def fixture_name(m: Match) -> str:
    return match_name(m.opponent, m.home)


def fixture_suffix(m: Match) -> str:
    """What a fixture's title says about its date: postponed, or not yet fixed."""
    if m.postponed:
        return " (postponed)"
    if not m.date_confirmed:
        return " (date not confirmed)"
    return "" if m.kickoff_confirmed else " (time not confirmed)"


# --- per match ---------------------------------------------------------------

def notices_for(m: Match, o: Outcome, points: int, now: datetime,
                sale_seen: datetime | None, sold_out_seen: datetime | None,
                problem_seen: datetime | None = None) -> list[Notice]:
    """The events for one match: its sale (or sell-out, or "check this") and its fixture."""
    notes = _notes(m, o)
    seen = sale_seen or now
    ahead = o.opens is not None and o.opens > seen  # a sale already over when first found needs no reminder
    match o.kind:
        case "sale" | "predicted_sale" if ahead:
            out = [_sale(m, o, points, seen, notes)]
        case "sold_out_before_you" if ahead:
            out = [reminder(f"sale:{m.key}", f"{m.opponent} sold out at {o.sold_out_stage} (you have {points})",
                            o.opens, notes, alarms=[])]
        case "exchange_open":
            out = _exchange(m, o, (sold_out_seen or now) + SOON, notes)
        case "unreadable":
            first = problem_seen or now
            why = f"couldn't read a sale line: “{m.unreadable[0]}”" if m.unreadable else "found no sale dates in it"
            out = [check_this(f"check:{m.key}", m.url, f"{fixture_name(m)} tickets", first,
                              first if o.urgent else None, why)]
        case _:
            out = []
    return [*out, *fixture(m)]


def fixture(m: Match) -> list[Notice]:
    """The match itself in the calendar (none until it has a date)."""
    if m.kickoff is None:
        return []
    return [Notice(f"fixture:{m.key}", f"⚽ {fixture_name(m)}{fixture_suffix(m)}",
                   m.kickoff, m.kickoff + timedelta(hours=2), [], m.url)]


def _where(m: Match) -> str:
    return "away" if not m.home else m.competition


def _notes(m: Match, o: Outcome) -> str:
    lines = [f"{s.label}: {spoken(s.opens)}" for s in m.stages]
    if o.pattern_note:
        lines.append(o.pattern_note)
    if o.stage is not None and o.stage.time_assumed:
        lines.append("time assumed 9am (the article gives no time)")
    lines.append(m.url)
    return "\n".join(lines)


def _sale(m: Match, o: Outcome, points: int, seen: datetime, notes: str) -> Notice:
    title = f"🎟️ {m.opponent} {_where(m)}: your sale {spoken(o.opens)} ({o.stage.label}, you have {points})"
    if o.kind == "predicted_sale":
        title += " (predicted: brackets not announced yet)"
    return reminder(f"sale:{m.key}", title, o.opens, notes, alarms=_sale_alarms(o.opens, seen))


def _sale_alarms(opens: datetime, seen: datetime) -> list[datetime]:
    """7pm a week, two days and one day before, then 30 and 5 minutes before it opens.

    Only those still ahead when the sale was first seen; one found too late for
    any of them rings two minutes after it was seen.
    """
    evenings = [at_london(opens.date() - timedelta(days=d), time(19, 0)) for d in (7, 2, 1)]
    wanted = [*evenings, opens - timedelta(minutes=30), opens - timedelta(minutes=5)]
    return [a for a in wanted if seen <= a < opens] or [seen + NOW_ALARM]


def _exchange(m: Match, o: Outcome, start: datetime, notes: str) -> list[Notice]:
    """The exchange is open to you; and, when the page says, the evening before it closes."""
    out = [reminder(f"exchange:{m.key}",
                    f"🎟️ {m.opponent} {_where(m)}: ticket exchange open to you (sold out at {o.sold_out_stage})",
                    start, notes)]
    if (closes := m.status.exchange_closes) is not None:
        eve = at_london(closes.date() - timedelta(days=1), time(19, 0))
        out.append(reminder(f"exchange_closing:{m.key}", f"🎟️ {m.opponent} exchange closes {spoken(closes)}",
                            eve, notes))
    return out


# --- one-off alerts and reminders ----------------------------------------------

def alert(key: str, title: str, notes: str, now: datetime) -> Notice:
    """A one-off "this changed" alert, five minutes from now."""
    return reminder(key, f"⚠️ {title}", now + SOON, notes, one_shot=True)


def moved(kind: str, key: str, opponent: str, old: str, new: str, url: str, now: datetime) -> Notice:
    """'⚠️ Fulham: kick-off moved Sat 26 Dec 3pm → Sun 27 Dec 2pm' (kind: kickoff_moved or sale_moved)."""
    what = "kick-off moved" if kind == "kickoff_moved" else "sale moved"
    old_s, new_s = spoken(datetime.fromisoformat(old)), spoken(datetime.fromisoformat(new))
    return alert(f"{kind}:{key}:{new}", f"{opponent}: {what} {old_s} → {new_s}", url, now)


def change_notices(changes: list[Change], m: Match, now: datetime) -> list[Notice]:
    """An alert for each change spotted in one match."""
    return [moved(c.kind, m.key, m.opponent, c.old, c.new, m.url, now) for c in changes]


def points_due(key: str, opponent: str, kickoff: datetime, worth: int | None, now: datetime) -> Notice | None:
    """'Update your points' once the club has credited them: never before."""
    landed = at_london(kickoff.date() + POINTS_LAND_AFTER, time(9, 0))
    if not landed <= now <= landed + POINTS_STALE_AFTER:
        return None
    start = landed if now - landed < SOON else now + SOON
    title = (f"Points for {opponent} ({kickoff.day} {kickoff:%b}) should be on your account: "
             f"if you went (worth {worth if worth is not None else '?'}), run albion points <n>")
    return reminder(f"points:{key}", title, start, one_shot=True)


def check_this(key: str, url: str, title: str, first_seen: datetime, soonest: datetime | None,
               reason: str = "") -> Notice:
    """'Check this ticket article': 8.30 the next morning, or at once if something is due sooner."""
    start = at_london(first_seen.date() + timedelta(days=1), time(8, 30))
    if soonest is not None and soonest < start:
        start = first_seen + SOON
    return reminder(key, f"Check this ticket article: {title}", start, f"{reason}\n{url}" if reason else url,
                    why=reason)


def import_due(last: datetime, now: datetime) -> datetime:
    """When to suggest saving the ticket pages again: 7pm three weeks after the last
    import, then a week later each time it passes undone (kept for a day after ringing)."""
    due = at_london(last.date() + IMPORT_EVERY, time(19, 0))
    while due + timedelta(days=1) < now:
        due += IMPORT_NAG
    return due


def import_reminder(last: datetime, now: datetime) -> Notice:
    """'Save the ticket pages and import them': sale dates appear there before the club's news."""
    return reminder(IMPORT_KEY, "📄 Save the Away and Home ticket pages, then run albion import",
                    import_due(last, now),
                    "The ticket site lists sale dates before the club's news, and the tool never visits it.\n"
                    "Save each page as a PDF in your browser, then:\n"
                    "albion import ~/Desktop/Buy\\ Tickets*.pdf")
