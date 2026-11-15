"""`albion upcoming`: every match to come, grouped by what it means for you.

Each match falls into exactly one section (`section_of`), and each section
says how its table looks (`SECTIONS`), so the rendering is one loop.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import venues
from .display import day, dim, match_cells, table, title, when
from .notices import import_due
from .records import SEASON_TICKET, last_import
from .rules import sold_out_text
from .store import MatchRecord, State

SOON = timedelta(days=7)  # a sale this close stands out
PREDICTED_NOTE = "Predicted: your usual day, until the club announces the points brackets."

type Row = Callable[[str, MatchRecord], list[str]]


@dataclass(frozen=True)
class Section:
    title: str
    header: list[str]  # the columns before (lead) and after the shared match cells
    lead: Row = lambda key, rec: []
    tail: Row = lambda key, rec: []
    style: Callable[[MatchRecord, datetime], dict] = lambda rec, now: {}
    sort: Callable[[MatchRecord], str] = lambda rec: rec.kickoff_iso
    empty: str | None = None  # shown when the section has no matches; None leaves it out
    footnote: Callable[[list[list[str]]], str | None] = lambda rows: None


def _ground(key: str, rec: MatchRecord) -> list[str]:
    s = rec.summary
    where = venues.location(s.get("opponent", ""), s.get("home", False), rec.venue, {})
    return [where.address.split(",")[0] if where else "—"]


def _sold_out(key: str, rec: MatchRecord) -> list[str]:
    level = sold_out_text(rec.sold_out_at()).removeprefix("sold out ")
    exchange = " · exchange open to you" if rec.summary.get("kind") == "exchange_open" else ""
    return [level + exchange]


def _soon(rec: MatchRecord, now: datetime) -> dict:
    opens = datetime.fromisoformat(rec.summary["opens"])
    return {"fg": "yellow", "bold": True} if opens - now <= SOON else {}


SECTIONS: dict[str, Section] = {  # in display order
    "tickets": Section("You have tickets", ["Match", "Comp", "Kick-off", "Ground"], tail=_ground,
                       style=lambda rec, now: {"fg": "green", "bold": True}),
    "season": Section("Season ticket · home league", ["Match", "Comp", "Kick-off"]),
    "to_come": Section("Sales to come", ["Your sale", "Match", "Comp", "Kick-off", "Note"],
                       lead=lambda key, rec: [when(rec.summary["opens"])],
                       tail=lambda key, rec: ["predicted" if rec.summary.get("kind") == "predicted_sale" else ""],
                       style=_soon, sort=lambda rec: rec.summary["opens"],
                       empty="None yet: the next check will pick them up when the club announces them.",
                       footnote=lambda rows: PREDICTED_NOTE if any(r[-1] == "predicted" for r in rows) else None),
    "on_sale": Section("On sale now", ["Opened", "Match", "Comp", "Kick-off"],
                       lead=lambda key, rec: [day(rec.summary.get("opens"))]),
    "sold_out": Section("Sold out", ["Match", "Comp", "Kick-off", "Sold out"], tail=_sold_out,
                        style=lambda rec, now: {"dim": True}),
    "no_dates": Section("No sale dates yet", ["Match", "Comp", "Kick-off"]),
    "look": Section("Needs a look", ["Match", "Comp", "Kick-off"]),
}

_SALE = ("sale", "predicted_sale")
_SOLD = ("sold_out", "sold_out_before_you", "exchange_open")


def section_of(key: str, rec: MatchRecord, state: State, now: datetime) -> str:
    """The one section a match belongs in, most personal first."""
    kind = rec.summary.get("kind", "")
    opens = rec.summary.get("opens")
    if key in state.have_tickets:
        return "tickets"
    if kind == SEASON_TICKET:
        return "season"
    if kind == "unreadable":
        return "look"
    if kind in _SALE and opens and datetime.fromisoformat(opens) > now:
        return "to_come"
    if kind in _SOLD or rec.sold_out_at():
        return "sold_out"
    return "on_sale" if kind in (*_SALE, "on_sale") else "no_dates"


def _to_come(rec: MatchRecord, now: datetime) -> bool:
    """Not yet played: no date, a date ahead, or postponed (its old date may have passed)."""
    return rec.kickoff is None or rec.news.get("postponed") or rec.kickoff >= now


def render(state: State, now: datetime) -> str:
    groups: dict[str, list[tuple[str, MatchRecord]]] = {name: [] for name in SECTIONS}
    for key, rec in state.matches.items():
        if _to_come(rec, now):
            groups[section_of(key, rec, state, now)].append((key, rec))
    points = state.points if state.points is not None else "?"
    blocks = []
    for name, sec in SECTIONS.items():
        items = sorted(groups[name], key=lambda item: sec.sort(item[1]))
        heading = title(sec.title + (f" · you have {points} points" if name == "to_come" else ""))
        if not items:
            if sec.empty:
                blocks.append(f"{heading}\n{sec.empty}")
            continue
        rows = [[*sec.lead(k, r), *match_cells(k, r), *sec.tail(k, r)] for k, r in items]
        body = table(rows, sec.header, [sec.style(r, now) for _, r in items])
        note = sec.footnote(rows)
        blocks.append("\n".join(filter(None, [heading, body, note and dim(note)])))
    checks = sorted(k for k in state.events if k.startswith("check:"))
    if checks:
        lines = [f"{k}  {dim(f'albion dismiss {k}')}" for k in checks]
        blocks.append("\n".join([title("Check this reminders"), *lines]))
    last = f"Last checked {when(state.last_check)}." if state.last_check else "Not checked yet: run albion check."
    if (imported := last_import(state)) is not None:
        last += f"\nTicket pages last imported {day(imported)}; next reminder {day(import_due(imported, now))}."
    return "\n\n".join([*blocks, dim(last)])
