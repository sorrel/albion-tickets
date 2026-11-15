"""Shared pieces of terminal output: dates, competition names, match cells, tables.

Widths are always measured on plain text and styling applied afterwards,
since an ANSI escape takes no columns.
"""
from datetime import datetime

import click

from . import config
from .model import short_name
from .store import MatchRecord

_COMP = {"Premier League": "PL", "UEFA Europa League": "Europa", "UEFA Conference League": "Conference",
         "UEFA Champions League": "Champions"}


def when(moment: datetime | str | None) -> str:
    """'2026-12-02T20:15…' → 'Wed 02 Dec 20:15' (two-digit days, so columns line up)."""
    if not moment:
        return "—"
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return f"{moment.astimezone(config.TZ):%a %d %b %H:%M}"


def day(moment: datetime | str | None) -> str:
    """As `when`, without the time."""
    return when(moment)[:10] if moment else "—"


def comp(name: str) -> str:
    """A competition's short name for tables: 'UEFA Conference League' → 'Conference'."""
    return _COMP.get(name, name)


def match_cells(key: str, rec: MatchRecord) -> list[str]:
    """The Match, Comp and Kick-off cells every match table shares."""
    s = rec.summary
    if rec.news.get("postponed"):
        kickoff_cell = "postponed"
    else:  # "?" marks a date or time the club hasn't fixed yet
        unsure = not (s.get("kickoff_confirmed", True) and s.get("date_confirmed", True))
        kickoff_cell = when(rec.kickoff) + ("?" if unsure else "")
    return [short_name(s.get("opponent", key), rec.home), comp(s.get("competition", "")), kickoff_cell]


def table(rows: list[list[str]], header: list[str], styles: list[dict] | None = None) -> str:
    """Rows under a bold header and a dim rule; each row's style (if any) applied last."""
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
    styles = styles or [{}] * len(rows)
    styled = (click.style(line(r), **st) if st else line(r) for r, st in zip(rows, styles, strict=True))
    rule = "─" * len(line(["x" * w for w in widths]))
    return "\n".join([click.style(line(header), bold=True), click.style(rule, dim=True), *styled])


def title(text: str) -> str:
    return click.style(text, fg="yellow", bold=True)


def dim(text: str) -> str:
    return click.style(text, dim=True)
