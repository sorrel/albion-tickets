"""`albion history`: tracked matches by season, with the points each sale needed and where it sold out.

The year-on-year record: kick-off, worth, the Tue/Wed/Thu points brackets,
your sale, and the level it sold out at.
"""
from datetime import date
from itertools import pairwise

import click

from .display import comp, day, table, title, when
from .model import season_of, short_name
from .rules import sold_out_tier
from .store import MatchRecord, State, by_season

HEADER = ["Kick-off", "Match", "Comp", "Worth", "Tue / Wed / Thu", "Your sale", "Sold out at"]


def render(state: State, season: str | None, show_all: bool, verbose: bool, today: date) -> str:
    """The chosen season (default: this one, else the latest recorded), or every season."""
    seasons = by_season(state)
    if not seasons:
        return "No matches tracked yet: run albion check."
    current = season_of(today)
    if show_all:
        wanted = list(seasons)
    else:
        wanted = [season or (current if current in seasons else max(seasons))]
    return "\n\n".join(_season(sn, seasons.get(sn, []), state.points if sn == current else None, verbose)
                       for sn in wanted)


def _season(season: str, recs: list[MatchRecord], points: int | None, verbose: bool) -> str:
    label = season.replace("-", "–")
    if not recs:
        return f"No matches recorded for {label}."
    lines = [title(f"{label} season" + (f" · you have {points} points" if points is not None else "")),
             table([_row(r) for r in recs], HEADER)]
    moves = [f"{r.opponent} kick-off moved: {when(old)} → {when(new)} (noticed {when(seen)})"
             for r in recs for (old, _), (new, seen) in pairwise(r.kickoffs)]
    if moves:
        lines += ["", title("Kick-off changes"), *moves]
    if verbose:
        for r in recs:
            lines += ["", *_stages(r)]
    return "\n".join(lines)


def _row(rec: MatchRecord) -> list[str]:
    s = rec.summary
    if rec.brackets:
        brackets = " / ".join(rec.brackets[:3])
    else:
        brackets = "not announced" if any(st.get("pending") for st in rec.stages) else "—"
    return [when(rec.kickoff) + ("" if s.get("kickoff_confirmed", True) else "?"),
            short_name(rec.opponent, rec.home), comp(s.get("competition", "")),
            str(s["worth"]) if s.get("worth") is not None else "—",
            brackets, day(rec.your_sale), sold_out_tier(rec.sold_out_at())]


def _stages(rec: MatchRecord) -> list[str]:
    """--verbose: every sale stage, with yours marked."""
    lines = [click.style(f"{rec.opponent} ({'home' if rec.home else 'away'})", bold=True)]
    for st in rec.summary.get("stages", []):
        mine = "  ← your stage" if st["label"] == rec.summary.get("your_stage") else ""
        lines.append(f"  {when(st['opens'])}  {_stage_name(st)}{mine}")
    return lines


def _stage_name(st: dict) -> str:
    if st.get("min_points") is not None:
        return f"STHs/1901 with {st['min_points']}+ points"
    return st["label"] + (" (points brackets not announced yet)" if st.get("pending") else "")
